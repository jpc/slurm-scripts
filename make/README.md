## Use Makefiles to manage SLURM preprocessing jobs

This is a prototype of a mechanism that allows one to use Makefiles to schedule data preprocessing jobs on a SLURM
cluster. It coalesces separate tasks together and sends many of them in a single SLURM job while letting `make` take
care of dependency tracking.

An example Makefile:
```makefile
.SUFFIXES:

A: B1 B2 B3 B4
  echo "Doing $@"

B%: C%
  echo "Doing $@"

C%:
  echo "Doing $@"
```

To use it you need to run the job scheduler (using GNU parallel here instead of SLURM so the example is portable):

```bash
./build-send-task
python jobscheduler.py parallel
```

`jobscheduler` uses the first argument to choose the "cluster type" and all the rest of the arguments get passed to
the specially configured `make`. On a SLURM cluster you can use this:

```bash
HUGGINGFACE_LOCAL_ONLY=1 ~/slurm-scripts/make/bin/slurm-make all_vad
```

The default job size is set to `4` so it will run all the `C` tasks concurrently, then all the `B`s and finally it will
run the `A` (after a bit of delay – it waits a few seconds for more tasks to avoid launching a mostly empty job).

All of this is behaving mostly like normal `make -j` but with a twist to allow us to queue all the commands to a job
management system like SLURM and wait for them to finish. Since this is all built around regular `make` you can for example
run `make -n all_vad|wc -l` to check how many tasks would need to run to complete the `all_vad` goal.

### Future work

This is an MVP so a lot of stuff is missing.

The `send-task` is a quick hack written in C because launching 1024 Python instances (to feed 512 GPUs at 2 jobs per GPU)
was bringing the cluster file-system to it's knees (Python probes too many files when it `import`s stuff). Statically
linked `send-task` let's you submit a 1000 tasks in 1.5s.

Bugs:

- The job server port is hardcoded so only one user per machine (and no security). I suspect it would be best to make  
  the job scheduler be a wrapper around `make` so we can use UNIX domain sockets (maybe even pipes?) to securely  
  commnunicate between the scheduler and `send-task`.
- The individual task return codes are not extracted and the batch jobs never fail (unless the whole SLURM job times  
  out or is cancelled) so the return codes we give back to `make` are often incorrect.
- Everything assumes the repo is cloned in `~/slurm-scripts`.

Missing features:

- There should be some way to sort the jobs by kind and apply different SLURM job settings (tasks per GPU, timeouts)
- Would be nice to have some kind of benchmarking support to figure out the optimal jobs_per_gpu and batch_sizes
- The `stderr` and `stdout` from each of the tasks could be printed to the `make` console
- The CherryPy webserver is multi-threaded and needs an OS thread to keep track of each task. Replacing this with an  
  asyncio based web server (`aiohttp` or [`quart`](https://github.com/pallets/quart)) would lower the resource usage a lot.
- Even with the optimized SHELL override trick `make` still spawns a new OS process for each task just to wait on a TCP
  socket to track it's completion. Could be interesting to add our jobscheduler protocol support to GNU make and
  avoid all these process spawns.
