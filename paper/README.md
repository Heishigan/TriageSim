# Paper experiments

Settings and analysis for the paper "TriageSim: A Multi-Agent Framework for Evaluating LLM
Clinical Reasoning in Emergency Triage of Older Adults" (1000 older adults admitted after a fall,
MIMIC-IV 3.1, MIMIC-IV-ED 2.2 and MIMIC-IV-Note 2.2).

| File | Condition |
|---|---|
| `configs/main_chart_qwen38.yaml` | Chart review |
| `configs/main_mcq_qwen38.yaml` | Multiple-choice vignette |
| `configs/main_arrival_qwen38.yaml` | Arrival information only |
| `configs/main_similar_qwen38.yaml` | Retrieved similar cases |
| `configs/main_interview_qwen38.yaml` | Interview |
| `configs/main_personas_qwen38.yaml` | Interview with personas |
| `configs/pilot_*.yaml` | 20-case pilots of the two chart-review variations |

To repeat the study:

1. Build the cohort with `configs/cohorts/elderly_falls.yaml` and its case files
   (see the main README).
2. In each file above, set `cohort` to the name of your cohort folder.
3. Pull the models and run each experiment:
   `uv run triagesim models pull --experiment paper/configs/<file>.yaml`, then
   `uv run triagesim run --experiment paper/configs/<file>.yaml`.
4. Compute the statistics (aggregate numbers only, no patient data):
   `uv run --frozen --with scipy==1.18.1 --with pingouin==0.7.0 python paper/paper_stats.py > outputs/paper_stats.json`

The paper's runs used one NVIDIA L40S GPU (46 GB) with Ollama; models, temperatures, seeds and
prompts are in the files. Run outputs contain patient-level data and must not be shared.
