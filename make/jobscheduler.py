# SPDX-FileCopyrightText: 2024 Jakub Piotr Cłapa <jpc@collabora.com>
# SPDX-License-Identifier: MIT
import cherrypy

import math
import os
import queue
import subprocess
import sys
import tempfile
import threading
import time

class TaskManager:
    queue_delay = 30
    reaper_period = 5

    def __init__(self):
        self.task_queue = queue.Queue()
        self.job_queue = queue.Queue()
        self.job_size = self.optimal_job_size()

        threading.Thread(target=self._scheduler, daemon=True).start()
        threading.Thread(target=self._reaper, daemon=True).start()

    def run_task(self, spec):
        q = queue.SimpleQueue()
        self.task_queue.put((q, spec))
        return q.get()

    def schedule_tasks(self, tasks):
        raise NotImplemented()

    def job_statuses(self, jobids):
        raise NotImplemented()

    def optimal_job_size(self):
        raise NotImplemented()

    def _scheduler(self):
        while True:
            tasks = []
            deadline = None
            for i in range(self.job_size):
                try:
                    ev, spec = self.task_queue.get(timeout=deadline - time.time() if deadline else None)
                    tasks.append((ev, spec['argv']))
                    deadline = time.time() + self.queue_delay
                except queue.Empty:
                    break
            # print(f'Scheduling {len(tasks)} tasks...')
            jobid = self.schedule_tasks([' '.join(x[1]) for x in tasks])
            self.job_queue.put((jobid, tasks))
            print(f'Scheduled {len(tasks)} tasks as {jobid}')

    def _reaper(self):
        jobs = {}
        while True:
            try:
                jobid, tasks = self.job_queue.get(timeout=self.reaper_period if jobs else None)
                jobs[jobid] = tasks
            except queue.Empty:
                # reap finished jobs and send back statuses
                for jobid,status in self.job_statuses(jobs.keys()).items():
                    print(f"Reaping jobs: {jobid} ({len(jobs[jobid])} tasks) with: {status}")
                    for ret_chn, args in jobs[jobid]:
                        ret_chn.put(status)
                    del jobs[jobid]

class SlurmTaskManager(TaskManager):
    ACCOUNT = "laionize" # "cstdl"
    JOB_NODES = 4
    JOBS_PER_GPU = 2
    JOBS_PER_NODE = JOBS_PER_GPU * 4
    TIME_LIMIT = "00:20:00"
    CLUSTER = "booster"

    def optimal_job_size(self):
        return self.JOB_NODES * self.JOBS_PER_NODE

    def optimal_config(self, N):
        """
        Return the optimal (job_nodes, jobs_per_gpu) config for the given number of tasks `N`.

        >>> manager = SlurmTaskManager()
        >>> manager.optimal_config(1)
        (1, 1)
        >>> manager.optimal_config(2)
        (1, 1)
        >>> manager.optimal_config(4)
        (1, 1)
        >>> manager.optimal_config(6)
        (1, 2)
        >>> manager.optimal_config(8)
        (1, 2)
        >>> manager.optimal_config(16)
        (2, 2)
        >>> manager.optimal_config(32)
        (4, 2)
        """
        if N == self.optimal_job_size():
            return self.JOB_NODES, self.JOBS_PER_GPU
        if N < self.JOBS_PER_NODE:
            jobs_per_gpu = math.ceil(N / 4)
            return 1, jobs_per_gpu
        return math.ceil(N / self.JOBS_PER_NODE), self.JOBS_PER_GPU

    def schedule_tasks(self, tasks):
        job_nodes, jobs_per_gpu = self.optimal_config(len(tasks))
        with tempfile.NamedTemporaryFile(delete=False, dir=".") as task_list:
            task_list.write(('\n'.join(tasks + [''])).encode('utf8'))
            task_list.close()
        result = subprocess.run(["sbatch", "--parsable", "/dev/stdin"], input=f"""#!/bin/bash
#SBATCH --account={self.ACCOUNT}
#SBATCH --nodes={job_nodes}
#SBATCH --ntasks={job_nodes * 4 * jobs_per_gpu}
#SBATCH --ntasks-per-gpu={jobs_per_gpu}
#SBATCH --output=out.%j
#SBATCH --error=err.%j
#SBATCH --time={self.TIME_LIMIT}
#SBATCH --partition={self.CLUSTER}

srun -A {self.ACCOUNT} --cpu-bind=none,v --accel-bind=gn --job-name=interactive \\
     ~/slurm-scripts/one-slurm-batch-job.sh {task_list.name}
""".encode('utf8'), capture_output=True)
        if result.returncode != 0:
            print("STDERR: \n" + result.stderr)
            result.check_returncode()
        jobid = int(result.stdout)
        os.symlink(task_list.name, f"tasks.{jobid}")
        return jobid

    _sample_sacct_output = """9501614|COMPLETED
9501614.batch|COMPLETED
9501614.0|COMPLETED
9544438|TIMEOUT
9544438.batch|CANCELLED
9544438.0|CANCELLED
9619422_0|TIMEOUT
9619422_0.batch|CANCELLED
9619422_0.0|FAILED
9622324_46|COMPLETED
9622324_46.batch|COMPLETED
9622324_46.0|COMPLETED
"""

    @staticmethod
    def _parse_sacct_output(jobids, stdout):
        """
        Returns the status of the given jobs extracted from the `sacct` output.

        >>> SlurmTaskManager._parse_sacct_output("9622442 9619422 9544438 9501614".split(" "), SlurmTaskManager._sample_sacct_output)
        {9501614: 0, 9544438: 1}
        """
        jobids = set(jobids)
        statuses = {}
        for ln in stdout.split('\n'):
            if not ln: break
            jobid,status = ln.split('|')
            if " " in status: status = status.split(" ")[0]
            if jobid in jobids:
                if status in ['COMPLETED', 'CANCELLED', 'TIMEOUT', 'FAILED']:
                    statuses[int(jobid)] = 0 if status == 'COMPLETED' else 1
        return statuses

    def job_statuses(self, jobids):
        jobids = [str(x) for x in jobids]
        result = subprocess.run(['sacct', '-j', ','.join(jobids), '-o', 'jobid,state', '-n', '-P'], capture_output=True)
        result.check_returncode()
        stdout = result.stdout.decode('utf8')
        return self._parse_sacct_output(jobids, stdout)

class GNUParallelTaskManager(TaskManager):
    queue_delay = 3
    reaper_period = .2

    def optimal_job_size(self):
        return 4

    def schedule_tasks(self, tasks):
        proc = subprocess.Popen(
            ["parallel", "{}"],
            stdin=subprocess.PIPE
        )
        proc.stdin.write(('\n'.join(tasks + [''])).encode('utf8'))
        proc.stdin.close()
        return proc

    def job_statuses(self, jobids):
        statuses = {}
        for proc in jobids:
            rc = proc.poll()
            if rc is not None:
                print(f'{proc} exited with code {rc}')
                statuses[proc] = rc
        return statuses

class JobScheduler(object):
    @cherrypy.expose
    @cherrypy.tools.json_in()
    @cherrypy.tools.json_out()
    def index(self):
        rc = manager.run_task(cherrypy.request.json)
        return { 'rc': rc }

if __name__ == '__main__':
    mode = sys.argv[1] if len(sys.argv) > 0 else "parallel"

    if mode == 'slurm':
        manager = SlurmTaskManager()
    elif mode == 'test':
        import doctest
        errs, total = doctest.testmod()
        sys.exit(1 if errs > 0 else 0)
    elif mode == "parallel":
        manager = GNUParallelTaskManager()

    cherrypy.config.update({
        # FIXME: randomly generate the port (set this to `0`) and pass it to the Makefile
        'server.socket_port': 4444,
        # this effectively limits the parallelism of make -j
        'server.thread_pool': 1024,
        # this is 5 by default and would starve the 1024 threads
        'server.socket_queue_size': 1024,
        # the individual request logs are not that intersting (we still log each job start/end)
        'log.screen': False,
    })
    cherrypy.tree.mount(JobScheduler(), '', {})

    cherrypy.engine.signals.subscribe()
    cherrypy.engine.start()
    # We can use this in the future to retrieve the random port
    # _host, port = cherrypy.server.bound_addr
    # print("Port:", port)
    cherrypy.engine.block()
