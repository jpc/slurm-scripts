# Juwels Booster scripts

These are my script that help you run large training runs on the Juwels Booster cluster.

The cluster configuration for Open Source projects allows you to run up to 24 concurrent jobs
on up to 24 nodes each for up to 6 hours. Each node has 4 A100 GPUs with 40GB of RAM. The maximum
amount of jobs in the queue at the same time is 64 (regardless of their size).

Our jobs also have low priority so we have to "squeeze in" between longer-running higher priority jobs.
In practice this means it's often a lot easier to schedule 24 jobs with 8 nodes for 20
minutes each (768 GPUs) than it is to run a single, much smaller, 8 node training run for 6 hours. The 
[LLview](https://llview.fz-juelich.de/juwels_booster/index.html?config=/data/ll/user&project=cstdl#page=live&sort_col=Userid&sort_dir=asc) tool is very useful to get a feel for the available "windows of opportunity" at any given time.

## Training

To run a training job you can use `run-train`. You pass in the number of nodes you wish to
train on as the first argument (`8` in this example for a total of `32` GPUs). You can also
change the `TIME_LIMIT` and the `CLUSTER` (default is `booster` or `develbooster`) using env
variables. All the rest of the arguments form a command line that is going to be run on each node.
The script makes PyTorch Lightning happy by allowing each process to see all GPUs and making
sure we use Infiniband for communication.

TODO:
- automatic jobs resuming is not working (even if we enable sending the signals)

```bash
#!/bin/bash
TIME_LIMIT=02:00:00 ~/slurm-scripts/run-train 8 \
  python3 -m whisperspeech.train_multi \
    --task "t2s_up_wds_mlang_enclm small --frozen_embeddings_model vqmodel-medium-en+pl-512c-dim64.model" \
    --tunables="--cps_input --causal_encoder --warmup_steps=300 --encoder_depth_ratio=.75"
    --batch-size 8 --epochs 2 --lr-schedule wsd \
    --dataset-config=--vq_codes=513 \
    --training-data @librilight/librilight-t2s-train.dataset \
    --training-data "@wolnelektury-train.dataset --weight=.1" \
    --monitored-metric val_loss/dataloader_idx_2 \
    --validation-data @librilight/librilight-t2s-val-common-speakers.dataset \
    --validation-data @wolnelektury-val.dataset \
    --validation-data @librilight/librilight-t2s-val-unseen-speakers.dataset \
    --validation-data @youtube-cc-small-val.dataset \
    --validation-data @multilingual-librispeech-webdataset/mls-fr-t2s-val-unseen-speakers.dataset
```

## Batch processing

For running batch jobs you can use `run-batch` which works a bit similar to GNU Parallel.
You pass in the job list on stdin, it will run each job on a separate GPU (unless you set
`JOBS_PER_GPU` higher than 1) and save the stdout/stderr and job status to files in the
`outputs/` folder. The first argument (`24` in this case) specifies the number of allowed
concurrent jobs (the rest will be queued).

You can also configure `JOB_NODES` to synchronously spawn multiple nodes.
It allows you to utilize more GPUs since there is a maximum concurrent jobs limit but makes
your jobs larger so a bit more difficult to schedule. By default each job is the smallest
possible and only uses a single node.

```bash
find ./ -name '*.tar' \
  | CLUSTER=develbooster TIME_LIMIT=02:00:00 \
    ~/slurm-scripts/run-batch 24 \
    'python -m whisperspeech.extract_stoks --batch_size 16 --kind maxvad --vq_model ~/clapa1/scratch/vqmodel-medium-en+pl-512c-dim64.model $FILE'
```

Afterwards you can run this in the same folder to see the progress of each job (assuming you do have some progress bars):

```bash
watch ~/slurm-scripts/show-batch-outputs
```

## Hyperparameter tuning

This works just like batch processing above but we need to pacify Lightning and pretend we only run one task. The command
below will ultimately run 128 short training jobs, one per GPU and log them all to a separate `wandb` project.

```bash
seq 128 | \
  CLUSTER=booster TIME_LIMIT=00:20:00 ~/slurm-scripts/run-batch 24 \
    SLURM_NTASKS=1 python3 -m whisperspeech.train_multi \
    --task "t2s_up_wds_mlang_enclm" \
    --batch-size 64 --epochs 4 --lr-schedule wsd \
    --tunables="--causal_encoder --cps_input --random_finetune" \
    --dataset-config="--vq_codes=513" \
    --training-data '@libritts-r/libritts-r.dataset' \
    --monitored-metric val_loss/dataloader_idx_0 \
    --validation-data @librilight/librilight-t2s-val-common-speakers.dataset \
    --validation-data @wolnelektury-val.dataset \
    --validation-data @librilight/librilight-t2s-val-unseen-speakers.dataset \
    --load-from t2s_up_wds_mlang_enclm/oscar_yellowgreen.model \
    --wandb-task-name t2s_up_wds_mlang_enclm_ft_clean
```

## Jobs overview

These are 3 background commands I like to run in tmux to have an overview of what's happening on the cluster,
how my jobs are doing and to push the training progress to W&B (`booster` compute nodes do not have internet access).

```bash
watch "sinfo |grep '^booster\|develbooster'"
```

```bash
watch "squeue -u $USER --start -tcg,pd,r,cf"
```

```bash
while true; do wandb sync --sync-all wandb/; sleep 30; done
```

You can also `pip install nvitop` to get a good `nvtop` alternative without compiling anything:
```bash
nvitop -U # Unicode drawing does not work on the cluster for some reason
```

You can use `srun` to get a shell inside a running job:
```bash
srun --pty --overlap --jobid=9705459 /bin/bash
```

You can also use my helper script to quickly check the GPU utilization:
```bash
~/slurm-scripts/nvitop 9698154 # takes a job ID and runs nvitop there
```

## Python environment

Enable Python and setup a venv in under ~/$USER/env. Afterwards this gives you a good environment:
```bash
ml Stages/2023  GCCcore/.11.3.0 Python/3.10.4 parallel/20220722
. ~/$USER/env/bin/activate
```
