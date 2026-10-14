# Running TriageSim on a Slurm cluster

GPU work runs as batch jobs; the app can run on the login node (no GPU) to watch them
live through an SSH tunnel. Everything stays on the cluster.

## 1. Once: get the code and tools (login node)

```bash
git clone https://github.com/Heishigan/TriageSim.git && cd TriageSim
curl -LsSf https://astral.sh/uv/install.sh | sh     # uv: installs Python and packages
export PATH="$HOME/.local/bin:$PATH"                 # (add this line to ~/.bashrc)
uv sync                                              # creates .venv with everything
```

Ollama: if `ollama` is not available, install it in your home folder without admin rights:
```bash
mkdir -p ~/bin ~/ollama && cd ~/ollama
curl -fL https://ollama.com/download/ollama-linux-amd64.tgz | tar -xz   # bin/ and lib/
ln -sf ~/ollama/bin/ollama ~/bin/ollama && cd -
```

## 2. Once: the data (choose A or B)

**A. Copy a finished cohort (simplest).** Experiments only need the cohort folder with its
case files. Copy it from your PC (patient-level data: only between your own credentialed
machines, never into git):
```bash
scp -r "outputs/cohorts/elderly_falls_<time>" <you>@<cluster>:~/TriageSim/outputs/cohorts/
```
The Data page will show the MIMIC files as missing; experiments still run. Cohort building
and case review need the MIMIC files (option B).

**B. Link the MIMIC files** (needed to build cohorts and review cases on the cluster).
Link the MIMIC files you already have on the cluster into `data/` (no copies):
```bash
mkdir -p data/hosp data/ed data/note
ln -s /path/to/patients.csv.gz      data/hosp/patients.csv.gz
ln -s /path/to/diagnoses_icd.csv.gz data/hosp/diagnoses_icd.csv.gz
ln -s /path/to/edstays.csv.gz       data/ed/edstays.csv.gz      # ... triage, diagnosis, medrecon
ln -s /path/to/discharge.csv.gz     data/note/discharge.csv.gz
uv run triagesim cohort check                                    # all OK?
```
Missing files can be downloaded with your PhysioNet login, e.g.
`wget -N -c --user <physionet-user> --ask-password -P data/ed https://physionet.org/files/mimic-iv-ed/2.2/ed/medrecon.csv.gz`

## 3. Cohort and case files (a CPU job, ~10 minutes)

```bash
sbatch cluster/build_cases.sbatch configs/cohorts/elderly_falls.yaml
```
Build them once. All benchmark runs then use the same newest `elderly_falls_*` cohort,
so the same 100 cases (seed 42) are compared.

## 4. Models

Models are stored once in `~/.ollama/models` (Ollama's default, so models downloaded for
the thesis are reused) and shared by all jobs. If GPU nodes have no
internet, download on the login node first:
```bash
bash cluster/pull_models.sh configs/experiments/benchmark/interview_qwen25-32b.yaml
```

## 5. Run

```bash
sbatch cluster/run_experiment.sbatch configs/experiments/benchmark/chart_review_qwen25-32b.yaml
squeue -u $USER                       # queue
tail -f logs/triagesim_<jobid>.out    # progress, one line per finished case
```
Each job starts its own Ollama on the GPU node. Three minutes before the time limit the run
stops cleanly; continue with
`sbatch cluster/run_experiment.sbatch --resume outputs/runs/<run folder>`.

## 6. The app on a GPU node (download models and run from the browser)

```bash
sbatch cluster/ui.sbatch
cat logs/triagesim-ui_<jobid>.out      # shows the node and the tunnel command
```
Users cannot ssh into the GPU nodes on this cluster, so the app listens on the node's
internal address and you tunnel through the login node only. The log prints both steps:
on your laptop `ssh -N -L 8765:<node address>:<port> <you>@slurm-login.dsv.su.se`
(keep it open), then on the login node `cat ~/.triagesim/ui-<jobid>.url` and open that
address. It contains a random access token, readable only by you, so other cluster users
cannot open your app even though it is on the cluster network; the token is stored as a
browser cookie, so afterwards http://127.0.0.1:8765 is enough. Ollama stays on the node
itself. Everything works as on your PC: Models (downloads go to `~/.ollama/models`, shared
with batch jobs), New experiment, live runs, results. `scancel <jobid>` stops it and frees
the GPU; runs stopped that way can be resumed later.

## 7. Watch batch jobs in the app (optional)

On the login node: `uv run triagesim ui --no-browser --port 8765`
On your laptop: `ssh -L 8765:127.0.0.1:8765 <you>@<cluster>` and open http://127.0.0.1:8765.
Jobs running on GPU nodes appear as running (live view works); stop them with `scancel`.

## Adjust to your cluster

Edit the `#SBATCH` lines in `cluster/*.sbatch`: partition, account, memory and time limit.
The scripts ask for 10 hours, the per-job maximum of the `slurm-students` account. A job that
asks for more stays pending with `AssocMaxWallDurationPerJobLimit`; check your limit with
`sacctmgr show assoc where user=$USER format=Account,MaxWall` and override per job with
`sbatch --time=HH:MM:SS ...`.
On clusters that register GPUs as resources add e.g. `#SBATCH --gres=gpu:1` (this cluster's
`gpu` partition does not).
