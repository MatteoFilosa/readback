# Running on AMD Developer Cloud

The model is served by vLLM on an AMD Instinct MI300X through ROCm. The app, the checks and
DuckDB run on the CPU of the same machine.

## 1. GPU droplet

Create a droplet with one MI300X and an image that ships ROCm and Docker (the vLLM quick-start
image works too). Add your SSH key, then:

```bash
ssh root@<droplet-ip>
rocm-smi                      # the GPU should be listed
git clone <repo-url> cohort-scout && cd cohort-scout
cp .env.example .env
```

In `.env` set `LLM_API_KEY` to a random string and, for gated models, `HF_TOKEN`.

## 2. Model and app

```bash
docker compose -f docker-compose.yml -f docker-compose.amd.yml up -d --build
docker compose logs -f vllm   # wait for "Application startup complete"
```

The first start downloads the weights (about 145 GB for a 72B model in bf16). Pin the image
with `VLLM_IMAGE=rocm/vllm:<tag>` once a tag is known to work, so a rebuild does not change it.

Model choice is one variable, `LLM_MODEL`. A single MI300X holds a 70B-class model in bf16; a
24B to 32B model leaves more room for concurrent requests and answers faster.

## 3. Reach it

Both ports are bound to 127.0.0.1 on the droplet. Open a tunnel instead of exposing them:

```bash
ssh -L 8080:localhost:8080 -L 8000:localhost:8000 root@<droplet-ip>
```

The app is then at http://localhost:8080 and the model at http://localhost:8000/v1.

## 4. Evaluate

```bash
docker compose exec app python -m eval.run draft --out results/<model>.jsonl
docker compose exec app python -m eval.run score results/<model>.jsonl
```

Results land in `results/` on the droplet. Copy them back with `scp` and commit them.

## 5. Stop

```bash
docker compose -f docker-compose.yml -f docker-compose.amd.yml down
```

Destroy the droplet when done: a running GPU keeps consuming credits.
