#!/bin/bash

joblist=$1; shift

export TASKID="$(($SLURM_ARRAY_TASK_ID * $SLURM_NTASKS + $SLURM_PROCID + 1))"
export FILE="$(sed -n "${TASKID}p" $joblist)"
export CUDA_VISIBLE_DEVICES=$(($SLURM_LOCALID % 4))

echo arr:$SLURM_ARRAY_TASK_ID proc:$SLURM_PROCID/$SLURM_NTASKS task:$TASKID cuda:$CUDA_VISIBLE_DEVICES file:$FILE host:$(hostname)
mkdir -p outputs

[ -z "$FILE" ] && exit 0

oname="outputs/${FILE##*/}_$TASKID"

SECONDS=0
bash -c "$@" > "$oname.stdout" 2> "$oname.stderr"
echo "$?" > "$oname.retval"
echo "$SECONDS" > "$oname.walltime"
