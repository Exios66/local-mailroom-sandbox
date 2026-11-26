# Open 7B–14B models for text document intelligence on Modal vLLM

Retrieval date for every web page below: 2026-11-20. No weights were downloaded, and nothing was deployed. Scores are copied from the named card or blog; none of those pages state a sample size `n`. This pipeline consumes text: a search of `src/` found no raster, page-image, PyMuPDF, or pdf2image path, and the Modal serve path zeros image, video, and audio for Qwen3.5.

## Does Qwen 3.5 9B exist on Hugging Face as of 2026-11-20?

### Takeaway

Yes. The official post-trained checkpoint is `Qwen/Qwen3.5-9B`, announced 2026-03-02. It is a 9B-language-model multimodal (image-text-to-text) hybrid, Apache-2.0, with a native context of 262,144 tokens. There is no official 9B FP8 or AWQ sibling in the Qwen3.5 collection, and no later Qwen3.6 or Qwen3.8 9B was found. `Qwen/Qwen3-8B` remains the previous dense text checkpoint this repo still freezes for specialist cost evals.

### Cited Findings

- Official repo id `Qwen/Qwen3.5-9B`. The card calls it a causal language model with a vision encoder. Under "Language Model" it lists 9B parameters, hidden size 4096, 32 layers, layout `8 × (3 × (Gated DeltaNet → FFN) → 1 × (Gated Attention → FFN))`, and context length 262,144 natively, extensible to 1,010,000 with YaRN. The README front matter is `license: apache-2.0` and `pipeline_tag: image-text-to-text`, with base model `Qwen/Qwen3.5-9B-Base`. The LICENSE blob is the Apache License 2.0 text. — [Qwen/Qwen3.5-9B](https://huggingface.co/Qwen/Qwen3.5-9B); [README front matter](https://huggingface.co/Qwen/Qwen3.5-9B/blob/c202236/README.md); [LICENSE](https://huggingface.co/Qwen/Qwen3.5-9B/blob/main/LICENSE)
- The Qwen GitHub news line dated 2026-03-02 says `Qwen3.5-9B`, `Qwen3.5-4B`, `Qwen3.5-2B`, and `Qwen3.5-0.8B` are on the Hub and ModelScope. Earlier lines: 2026-02-16 first Qwen3.5 release (397B-A17B only); 2026-02-24 adds 122B-A10B, 35B-A3B, and 27B. Later lines add Qwen3.6-35B-A3B (2026-04-16), Qwen3.6-27B (2026-04-22), Qwen3.8-2.4T-A95B (2026-08-12), and Qwen3.8-27B (2026-08-14). No 9B appears in the 3.6 or 3.8 lines. — [QwenLM/Qwen3.5](https://github.com/QwenLM/Qwen3.5)
- The Qwen3.5 Hub collection lists `Qwen/Qwen3.5-9B` as Image-Text-to-Text, size bucket "10B", "Updated Mar 1", and lists `Qwen/Qwen3.5-9B-Base` the same way. The same collection lists official `-FP8` repos for 397B-A17B, 122B-A10B, 35B-A3B, and 27B, and `-GPTQ-Int4` for those four sizes. It does not list `Qwen/Qwen3.5-9B-FP8` or an official 9B AWQ. — [Qwen3.5 collection](https://huggingface.co/collections/Qwen/qwen35)
- Hub discussions on the 9B repo still ask for official FP8 weights. One is titled "Can we have a FP8 version?" (opened Apr 6); another, "FP8 WEIGHTS FOR THE MODEL", was opened Aug 14. The fetched headers do not print a year. A reply on an earlier thread points at a community repo `lovedheart/Qwen3.5-9B-FP8`, not a Qwen org repo. — [discussion 47](https://huggingface.co/Qwen/Qwen3.5-9B/discussions/47); [discussion 65](https://huggingface.co/Qwen/Qwen3.5-9B/discussions/65); [discussion 5](https://huggingface.co/Qwen/Qwen3.5-9B/discussions/5)
- Community quantizations, not official Qwen builds: `QuantTrio/Qwen3.5-9B-AWQ` lists a 12GiB AWQ dated 2026-03-02 in its README table and repeats the 9B / 262,144-token overview; `unsloth/Qwen3.5-9B-GGUF` lists a BF16 file at 17.9 GB, Q8_0 at 9.53 GB, and Q4_K_M at 5.68 GB; `axteam/Qwen3.5-9B-AWQ-8bit` is a community W8A16 compressed-tensors build of about 12.8 GB that says it was tested on vLLM 0.32.0, not on 0.29.0. — [QuantTrio README](https://huggingface.co/QuantTrio/Qwen3.5-9B-AWQ/resolve/main/README.md?download=true); [unsloth GGUF](https://huggingface.co/unsloth/Qwen3.5-9B-GGUF); [axteam AWQ-8bit](https://huggingface.co/axteam/Qwen3.5-9B-AWQ-8bit)
- The live 9B card still says "vLLM from the main branch of the open-source repository is required" and links a vLLM Qwen3.5 recipe, rather than naming v0.29.0. SGLang examples pass `--reasoning-parser qwen3`. Thinking mode is on by default. The card says to keep at least 128K context "to preserve thinking capabilities," and recommends 32,768 output tokens for most queries. Non-thinking sampling for general tasks is temperature 0.7, top_p 0.8, top_k 20, presence_penalty 1.5. — [Qwen/Qwen3.5-9B](https://huggingface.co/Qwen/Qwen3.5-9B)
- vLLM v0.17.0 release notes claim "Full support for the Qwen3.5 model family" with Gated Delta Networks, FP8 quantization, MTP, and reasoning-parser support. vLLM v0.29.0 was published 2026-09-09 and still mentions Qwen3.5: partial LoRA on Qwen3.5/3.6 GatedDeltaNet, Qwen3.5 embedding-module fixes, and a tuned FP8 fused-MoE kernel for Qwen3.5 on L40S. The 9B card's architecture is dense (FFN, not MoE); the fused-MoE note applies to the MoE siblings. — [vLLM v0.17.0](https://github.com/vllm-project/vllm/releases/tag/v0.17.0); [vLLM v0.29.0](https://github.com/vllm-project/vllm/releases/tag/v0.29.0)
- Language scores printed on the 9B card, in the `Qwen3.5-9B` column, with no `n` and no separate eval date: IFEval 91.5, IFBench 64.5, AA-LCR 63.0, LongBench v2 55.2, BFCL-V4 66.1. Comparators on that same table are GPT-OSS-120B, GPT-OSS-20B, Qwen3-Next-80B-A3B-Thinking, and Qwen3-30BA3B-Thinking-2507, not 7B–14B peers. Vision "document" scores on the same card (OmniDocBench1.5 87.7, MMLongBench-Doc 57.7, OCRBench 89.2) require page images. — [Qwen/Qwen3.5-9B](https://huggingface.co/Qwen/Qwen3.5-9B)
- A secondary deployment guide says official FP8 starts at Qwen3.5-27B, that no official AWQ exists for Qwen3.5 or later, and that Qwen3.6 shipped only as 27B and 35B-A3B. Treat that as a secondary summary; the collection listing above is the primary check. — [vdf.ai Qwen on-prem guide](https://vdf.ai/blog/qwen-on-premises-enterprise-deployment/)

### Inferences

- The name in this repo (`Qwen/Qwen3.5-9B`) matches a real Hub id. It is not a misremembered Qwen3-8B. The closest older text-only dense sibling that this checkout already serves is `Qwen/Qwen3-8B`, not a fictional missing 9B.
- The Hub "10B" collection tag and the card's "9B" language-model line are both printed. They were not reconciled to a vision-tower parameter count. The unsloth BF16 file at 17.9 GB is the right order of magnitude for a ~9B bf16 dump (about 18 GB) and is not an official safetensors total.
- v0.29.0 is later than the release that announced Qwen3.5 support, and its own notes still edit Qwen3.5 code, so a boot on the pinned image is plausible. The official card has not been updated to say v0.29.0 is enough, and this checkout marks the 9B row unverified. Those two facts stay open until a boot log exists.
- Vision document scores do not answer a text classification and field-extraction question. The language long-context and instruction-following numbers are the only published figures on that card that even resemble this workload, and they are not field F1 or JSON validity.

### Gaps

- No HTTP status check was made for the URL `https://huggingface.co/Qwen/Qwen3.5-9B-FP8`. Absence is inferred from the official collection listing and from users still requesting FP8 weights.
- Official safetensors byte size on `Qwen/Qwen3.5-9B` was not summed. The 17.9 GB figure is a community GGUF listing.
- v0.17.0's publish date was not retrieved. The 9B architecture was not diffed against the v0.29.0 model registry.
- The card does not publish `n`, a harness commit, or a JSON-schema / guided-decoding score.
- No Qwen3.6-9B or Qwen3.8-9B card was found. A model released under a different id after the GitHub news page was last indexed would have been missed.

## Which 7B–14B open models are serious document-intelligence alternatives in late 2026?

### Takeaway

The only peer in this size band with both a primary-source long-context table and a text-only (not vision) architecture, and that this repo can already serve on one L4, is IBM Granite 4.2 8B (`ibm-granite/granite-4.2-8b`, released 2026-08-25). The other serious serving choices already in the checkout are the older Qwen3 text checkpoints: `Qwen/Qwen3-8B`, `Qwen/Qwen3-8B-AWQ`, and `Qwen/Qwen3-14B-AWQ`. Published tables do not rank any of these on legal field extraction. Gemma 3 12B, Phi-4-mini, and DeepSeek-R1-Distill-Qwen-7B showed up as catalog or third-party names, not as late-2026 extraction evidence.

### Cited Findings

- `ibm-granite/granite-4.2-8b`: decoder-only dense transformer, 8B parameters, precision bfloat16, "Natively Supports 128K (Long-context extension to 512K)", Apache 2.0, release date August 25, 2026. Training text says reinforcement learning included "instruction following, tool use, general chat and structured output." It is not an image-text model. — [ibm-granite/granite-4.2-8b](https://huggingface.co/ibm-granite/granite-4.2-8b)
- Granite 4.2 8B column on that card, evaluations "based on NeMo Evaluator SDK", no `n`: IFBench (prompt) 79.33, RULER 64K 80.99, RULER 128K 71.41, MMLU-Pro 74.04, BFCL (v4) 52.39, LiveCodeBench v6 73.24. The IBM blog of the same family, published August 25, 2026 and last updated September 11, 2026, prints BFCL (v4) for the 8B as 50.29, not 52.39. Other shared cells in the fetched tables match. — [model card](https://huggingface.co/ibm-granite/granite-4.2-8b); [Granite 4.2 blog](https://huggingface.co/blog/ibm-granite/granite-4-2)
- A vLLM serve snippet on the Granite card uses `--context-length 131072`. — [ibm-granite/granite-4.2-8b](https://huggingface.co/ibm-granite/granite-4.2-8b)
- This checkout's Modal matrix, not a Hub measurement: `Qwen/Qwen3-8B` bf16 on L4 is capped at `max_model_len` 16384 because v0.29.0 raises at boot when one 32768-token request does not fit the KV pool; `Qwen/Qwen3-8B-AWQ` is the L4 row at 32768; `Qwen/Qwen3-14B` bf16 is noted as ~29GB and does not fit L4 (A100-40GB, 16384); `Qwen/Qwen3-14B-AWQ` is noted as an official Hub AWQ of ~10GB that fits one L4 at modest `max_num_seqs`, with the high-concurrency sorter runbook overriding to A100-40GB. — [config/models.yaml](../../../config/models.yaml); [config/runbooks/catalog.yaml](../../../config/runbooks/catalog.yaml)
- `Qwen/Qwen3.6-35B-A3B-FP8` exists and is later than the 9B (family news 2026-04-16). The fetched FP8 card says 35B total / 3B activated and context 262,144, extensible to 1,010,000. That is a 3B-active MoE, not a 7B–14B dense model, and it is not the id this repo pins for the mid tier (`Qwen/Qwen3.5-35B-A3B`). — [Qwen3.6-35B-A3B-FP8](https://huggingface.co/Qwen/Qwen3.6-35B-A3B-FP8); [QwenLM/Qwen3.5 news](https://github.com/QwenLM/Qwen3.5); [config/models.yaml](../../../config/models.yaml)
- Third-party, not an official card, and not the same benchmarks as Qwen's table: a FrozeBench page for `google/gemma-3-12b-it` lists IFEval prompt-level strict accuracy 81.0% and LongBench aggregate 46.2%, and its citation example says "Retrieved 2026-06-04" while the page also says "last evaluated: 2 weeks ago." An aggregator dates Gemma 3 12B to 2025-03-12. Those pages were not treated as a document-extraction result. The official Gemma card was not opened. — [FrozeBench](https://frozebench.com/models/google/gemma-3-12b-it); [AnotherWrapper comparison](https://anotherwrapper.com/tools/llm-pricing/gemma-3-12b-it/granite-4.2-8b)
- This checkout lists, without a late-2026 extraction table in the files read here: `microsoft/Phi-4-mini-instruct` (~8GB bf16, L4, `max_model_len` 32768), `deepseek-ai/DeepSeek-R1-Distill-Qwen-7B` (L4, 32768, "Reasoning model: parse content"), and `mistralai/Mistral-Small-3.1-24B-Instruct-2503` (~48GB bf16, A100-80GB). The 24B row is outside the 7B–14B band. The OpenRouter id `deepseek/deepseek-v4-flash` is mapped to the 7B distill for local vLLM; that mapping is a substitute, not a claim that the distill is DeepSeek V4. — [config/models.yaml](../../../config/models.yaml)

### Inferences

- For a text routing-plus-extraction workload, Granite 4.2 8B is the one new 2026 peer that is both text-only and already given a boot-valid L4 FP8 row in this repo. Qwen3-8B-AWQ and Qwen3-14B-AWQ are the incumbents with serving evidence in-tree, not models whose Hub cards were re-read on 2026-11-20.
- Qwen's IFEval 91.5 and Granite's IFBench (prompt) 79.33 are different benchmarks. Qwen's LongBench v2 55.2 and Granite's RULER 64K/128K are different benchmarks. Neither comparison picks a winner for class accuracy or field F1.
- Qwen's BFCL-V4 66.1 versus Granite's BFCL (v4) 52.39 (or 50.29 on the blog) is tool-calling, and this extract path does not use tools. It is a weak hint about instruction following, not a deployment decision.
- Gemma 3 12B is a 2025 model still appearing on late-2026 leaderboard mirrors. It is not a serious swap on the evidence gathered here. Phi-4-mini and the DeepSeek distill are catalogued options without an extraction table in this pass.

### Gaps

- No CUAD, ContractNLI, LegalBench, or JSON-schema validity paper comparing these checkpoints was retrieved.
- Official cards for `Qwen/Qwen3-8B`, `Qwen/Qwen3-8B-AWQ`, `Qwen/Qwen3-14B-AWQ`, Gemma 3, Phi-4-mini, and Mistral Small 3.1 were not opened on 2026-11-20. Parameter counts and licenses for those ids are not restated from memory.
- Granite's two BFCL (v4) figures (52.39 on the card, 50.29 on the blog) were not reconciled. No `n` is printed for either.
- No Gemma 4, Phi-5, or new Mistral 7B–14B card with an extraction or long-context table was found in this pass. That is a search miss, not a proof none exists.

## Weight, GPU, boot-valid context, and vLLM v0.29.0 incompatibilities

### Takeaway

Serve `Qwen/Qwen3.5-9B` only as text, with online FP8, on one 24GB GPU, at a provisional 16384 context, and treat the boot as unproven on v0.29.0. Serve Granite as the published `ibm-granite/granite-4.2-8b-fp8` checkpoint on one L4 at 32768 with the native `granite` reasoning parser. Keep `Qwen/Qwen3-8B-AWQ` when the requirement is a boot-validated 32768 context on one L4. Do not put 14B bf16 on an L4. H100 is the repo's GPU for published Qwen3 FP8 throughput rows, not a requirement to hold the 9B.

### Cited Findings

- App default in code: `DEFAULT_MODEL = "Qwen/Qwen3.5-9B"` on GPU `L4`, quantization `fp8` when no env override is set, plus `MODAL_VLLM_LIMIT_MM_PER_PROMPT` defaulting to `{"image":0,"video":0,"audio":0}`. `MAX_MODEL_LEN` defaults to 16384. The comment says the 9B has no published FP8 checkpoint, so this is online FP8. The same defaults exist for `Qwen/Qwen3.5-35B-A3B` and `Qwen/Qwen3.5-27B`. Image tag default `v0.29.0`. — [deploy/modal_vllm.py](../../../deploy/modal_vllm.py)
- `config/models.yaml` Qwen3.5 block: "No published FP8 Hub checkpoints — L4 uses online dynamic fp8." It says the deploy image must ship `causal_conv1d` and `fla` for Gated-DeltaNet kernels, and that without them vLLM silently falls back to slower PyTorch ops. The 9B row is L4, quantization `fp8`, `max_model_len` 16384, tp 1. Notes estimate online FP8 weights ~9.7GB and a ~12GB KV pool, say the card's 262144 is unreachable on one L4, and say "DoD incomplete until spend reopens (/health + VRAM peak)." The 35B-A3B row is L4:2, tp 2, 16384, online FP8. The 27B row is L40S, online FP8, 16384, "not an L4." — [config/models.yaml](../../../config/models.yaml)
- Same file, older Qwen3 rows this checkout treats as measured under DMR-056: L4 24GB at 0.90 utilization is ~21.6GB usable. `Qwen/Qwen3-8B` bf16 ~16GB, KV pool ~3.4GB, 32768 raises at boot, 16384 is the cap. `Qwen/Qwen3-8B-AWQ` ~4.4GB, 32768, quantization `awq`. `Qwen/Qwen3-8B-FP8` is a published checkpoint on H100 at 32768 with quantization left empty so vLLM auto-detects it. `Qwen/Qwen3-14B-FP8` is the same H100 pattern. `Qwen/Qwen3-14B` bf16 ~29GB, A100-40GB, 16384. `Qwen/Qwen3-14B-AWQ` ~10GB, matrix GPU L4 at 32768. FP8 is described as native on Hopper (H100) and Ada (L4), emulated on A100. AWQ/GPTQ 4-bit is described as running on Ampere (A10G/A100). — [config/models.yaml](../../../config/models.yaml)
- Granite rows in the same file: `ibm-granite/granite-4.2-8b-fp8` on L4, quantization `compressed-tensors`, `max_model_len` 32768, "~9.5GiB", "1xL4 FP8 boot-validates at 32k (~6GB headroom); bf16 32k FAILS". `ibm-granite/granite-4.2-8b` bf16 ~17.6GB, 16384 cap, 32768 fails on one L4. No AWQ/GPTQ for Granite 4.2. NVFP4/MXFP4 called Blackwell/Hopper-only, not for L4. Serve with `--reasoning-parser granite`. The note says `granite_thinking_parser` needs vLLM >= 0.30 and crash-loops 0.29.0 with a KeyError. No tool parser, because extract uses no tools. — [config/models.yaml](../../../config/models.yaml); [deploy/modal_vllm.py](../../../deploy/modal_vllm.py)
- Runbook variant `qwen35-9b` repeats model `Qwen/Qwen3.5-9B`, quantization `fp8`, `max_model_len` 16384, and the text-only multimodal limit. Variant `granite-fp8` repeats the compressed-tensors 32768 row and `MODAL_VLLM_REASONING_PARSER: granite`. AWQ variants pin `Qwen/Qwen3-8B-AWQ` at 16384 and 32768. The 14B AWQ sorter card sets `awq_marlin`, A100-40GB, 32768, fp8 KV, and `{"enable_thinking": false}`, with the comment "Avoid Granite-class 8192-token thinking / 408s." — [config/runbooks/catalog.yaml](../../../config/runbooks/catalog.yaml)
- The Modal skill for this repo says the pinned image is `vllm/vllm-openai:v0.29.0`, that L4 bf16 8B is boot-valid at 16384 and that AWQ/FP8 rows set 32768, and that async scheduling stays off when a run depends on structured outputs. The throughput example (`Qwen/Qwen3-8B-FP8` on H100, flashinfer, async scheduling on) is explicitly not the structured-output posture. — [.cursor/skills/modal/SKILL.md](../../../.cursor/skills/modal/SKILL.md)
- Qwen3.5 card: thinking on by default; disable with `chat_template_kwargs.enable_thinking` false on a vLLM/SGLang OpenAI API. SGLang reasoning parser name in the examples is `qwen3`. Context advice is at least 128K if thinking quality matters. — [Qwen/Qwen3.5-9B](https://huggingface.co/Qwen/Qwen3.5-9B)
- v0.29.0 highlights do not mention guided decoding, xgrammar, or outlines. They do say Model Runner V2 is the default and that some features still fall back to Model Runner V1. They do not say whether Qwen3.5 guided JSON is one of those features. — [vLLM v0.29.0](https://github.com/vllm-project/vllm/releases/tag/v0.29.0)

### Inferences

- One L4 or one A10G (the Ampere 24GB name this repo actually writes) can hold Qwen3-8B bf16 only at 16384, Qwen3-8B-AWQ at 32768, Granite FP8 at 32768, and, if the unverified estimate holds, Qwen3.5-9B online FP8 at 16384. One H100 is the written GPU for published Qwen3-8B-FP8 and Qwen3-14B-FP8, not for the 9B.
- A 14B bf16 weight of ~29GB does not fit a 24GB L4 or A10-class card. The 14B choice that fits one 24GB GPU is the AWQ checkpoint, and the high-concurrency sorter posture in this repo moves that AWQ to an A100-40GB anyway.
- Structured output on v0.29.0 is a repo operating rule (async scheduling off; no tool parser on the extract path), not a published Qwen3.5 compatibility matrix. Thinking mode is the incompatibility most likely to break JSON extraction: the model spends completion tokens on a trace, and the L4 context cap is 16384 while the card wants 128K for thinking.
- The vision tower is an incompatibility for this text server even though the weights are the right id. The repo already strips it with a zero multimodal limit. Serving a Qwen3-VL or Gemma vision checkpoint instead would add a modality this `src/` tree does not produce.
- Community AWQ, GGUF, and FP8 of the 9B are real files and are the wrong artifact for the current Modal rows. The rows point at `Qwen/Qwen3.5-9B` plus online `--quantization fp8`.

### Gaps

- No boot log on v0.29.0 for `Qwen/Qwen3.5-9B` at 16384 or any longer context, on L4, A10G, or H100. The 16384 cap is the checkout's provisional number.
- No source in this pass shows that vLLM 0.29.0 guided decoding accepts Qwen3.5 JSON schema, or which reasoning-parser string (`qwen3` versus empty) is valid on that image. The SGLang `qwen3` flag is from the model card, not from a v0.29.0 serve log.
- Official byte sizes for Granite FP8 (~9.5GiB) and Qwen3 AWQ (~4.4GB, ~10GB) are this repo's notes. The Granite FP8 Hub card was not opened.
- A10 (non-G) versus A10G memory was not checked against Modal's current GPU list. The checkout only names A10G.

## What this repo already pins or recommends

### Takeaway

Code, `config/models.yaml`, the runbook serving variant, and the CLI reference default the Modal app to `Qwen/Qwen3.5-9B` on one L4 with online FP8, text-only, context 16384 (SAND-077). The frozen specialist cost-eval posture is still `Qwen/Qwen3-8B` bf16 on one L4 at 16384. AWQ and Granite FP8 are improved-config runbooks, not the app default. The Modal skill file still says the default model is `Qwen/Qwen3-8B` and is stale relative to the checkout.

### Cited Findings

- `deploy/modal_vllm.py` module docstring: "App default (SAND-077): `Qwen/Qwen3.5-9B` on `L4`, online fp8, text-only." The frozen experiment posture is `MODAL_VLLM_MODEL=Qwen/Qwen3-8B` on L4, `max_containers=1`, scaledown 120, and the runbook id `l4-qwen3-8b`. `DEFAULT_MODEL = "Qwen/Qwen3.5-9B"`. — [deploy/modal_vllm.py](../../../deploy/modal_vllm.py)
- `config/models.yaml` `defaults.vllm` and `defaults.openrouter` are `Qwen/Qwen3.5-9B` and `qwen/qwen3.5-9b`. Ollama, llamacpp, and lmstudio stay on Qwen3-8B tags. The champion map `qwen/qwen3.7-flash` rewrites vLLM to `Qwen/Qwen3.5-9B`. Judge tier is `Qwen/Qwen3.5-27B` on an L40S. Mid specialist tier is `Qwen/Qwen3.5-35B-A3B` on L4:2. — [config/models.yaml](../../../config/models.yaml)
- Runbook catalog: `serving.baseline` is `Qwen/Qwen3-8B`, L4, image `v0.29.0`, `max_model_len` 16384, `max_num_seqs` 6. Variant `qwen35-9b` is the SAND-077 app default. Aliases `serve` / `default` point at `modal-vllm-serving`; aliases `l4` / `qwen` / `qwen3-8b` point at `l4-qwen3-8b`; alias `granite` points at `improved-granite-fp8`; alias `awq` points at `improved-awq`. The serving runbook text says one L4 serves `Qwen/Qwen3.5-9B` online FP8, text-only, 16384 context, `max_num_seqs` 6. — [config/runbooks/catalog.yaml](../../../config/runbooks/catalog.yaml)
- Generated CLI reference: model flag help text still gives `Qwen/Qwen3-8B` or `Qwen/Qwen3-8B-AWQ` as examples, and a later table says the model default is `Qwen/Qwen3.5-9B`. `--specialist-tier` documents mid as Qwen3.5-35B-A3B and full as Qwen3.5-27B. — [docs/cli-reference.md](../../cli-reference.md)
- `docs/SANDBOX-GUIDE.md` lists the `modal-vllm` profile model as `Qwen/Qwen3.5-9B` and `MODAL_VLLM_MODEL` default as `Qwen/Qwen3.5-9B`. — [docs/SANDBOX-GUIDE.md](../../SANDBOX-GUIDE.md)
- The skill read at task start still says `MODAL_VLLM_MODEL` default `Qwen/Qwen3-8B` and describes the frozen L4 specialist pins. That sentence does not match `DEFAULT_MODEL` in `deploy/modal_vllm.py`. — [.cursor/skills/modal/SKILL.md](../../../.cursor/skills/modal/SKILL.md); [deploy/modal_vllm.py](../../../deploy/modal_vllm.py)

### Inferences

- A deployment that follows the app default is already choosing `Qwen/Qwen3.5-9B` online FP8 on one L4 at 16384, without a published FP8 checkpoint and without a recorded healthy boot. A deployment that follows the frozen specialist runbook is still `Qwen/Qwen3-8B` bf16 at 16384. Those are two different decisions already encoded in the tree.
- Granite is a prepared swap (`improved-granite-fp8`), not the default. AWQ is the prepared way to get 32768 on one L4 for Qwen3-8B.

### Gaps

- Whether any live Modal app is actually running the 9B was not checked. `sandbox modal status` and any deploy were out of scope.
- `docs/cli-reference.md` showing both example ids is consistent with a generated reference that documents the flag and the default separately. It was not regenerated or diffed against the CLI parser in this pass.

## What published numbers already settle, and what this corpus still has to measure

### Takeaway

Published pages settle identity, license, architecture, native context, the lack of an official 9B FP8/AWQ in the Qwen collection, Granite's text-only 128K design, and this repo's boot caps for Qwen3-8B and Granite FP8. They do not settle which checkpoint should extract fields from these legal documents. The 9B versus Qwen3-8B-AWQ versus Granite FP8 choice moves only after a boot on v0.29.0 plus class accuracy, field F1, JSON validity, and context-overflow counts on this corpus.

### Cited Findings

- Identity and license of `Qwen/Qwen3.5-9B`, the 262,144 native context, thinking-by-default, and the 128K thinking advice are on the official card and the Apache LICENSE blob. The collection's FP8/GPTQ list omits a 9B quant. — [Qwen/Qwen3.5-9B](https://huggingface.co/Qwen/Qwen3.5-9B); [collection](https://huggingface.co/collections/Qwen/qwen35); [LICENSE](https://huggingface.co/Qwen/Qwen3.5-9B/blob/main/LICENSE)
- Granite 4.2 8B's parameter count, Apache 2.0 license, 128K native context, August 25, 2026 release, RULER scores, and IFBench (prompt) score are on the official card. Structured output is named as a training domain, not as a JSON pass rate. — [ibm-granite/granite-4.2-8b](https://huggingface.co/ibm-granite/granite-4.2-8b)
- This repo already records boot-valid caps it is willing to stand behind for the older rows: Qwen3-8B bf16 16384 on L4 (32768 raises), Qwen3-8B-AWQ 32768, Granite FP8 32768, Granite bf16 16384 with 32768 failing, Qwen3-14B bf16 not on L4. It explicitly does not stand behind the Qwen3.5-9B 16384 row until `/health` and a VRAM peak exist. — [config/models.yaml](../../../config/models.yaml)
- Vision document benchmarks on the Qwen3.5-9B card do not apply: `src/` has no raster path, and the serve default sets image, video, and audio limits to 0. — [Qwen/Qwen3.5-9B](https://huggingface.co/Qwen/Qwen3.5-9B); [deploy/modal_vllm.py](../../../deploy/modal_vllm.py)
- Instruction-following and long-context figures that do exist use different tests (Qwen IFEval / IFBench / LongBench v2 / AA-LCR versus Granite IFBench prompt / RULER) and publish no `n`. BFCL is tool use. The extract path sets no tool parser. — [Qwen/Qwen3.5-9B](https://huggingface.co/Qwen/Qwen3.5-9B); [Granite card](https://huggingface.co/ibm-granite/granite-4.2-8b); [config/models.yaml](../../../config/models.yaml)

### Inferences

- Already settled, so another public leaderboard will not change the deploy: the 9B id is real; it is multimodal and must be limited to text; there is no official 9B FP8 or AWQ to pin; Qwen3.6 and Qwen3.8 did not ship a 9B replacement in the sources found; 14B bf16 does not fit one L4; Granite's L4 path is the published FP8 repo at 32768 with parser `granite`; Qwen3-8B-AWQ is the in-tree way to get 32768 on one L4; H100 FP8 is a Qwen3 throughput row, not the 9B default.
- Not settled, and the decision between `Qwen/Qwen3.5-9B`, `Qwen/Qwen3-8B-AWQ`, and `ibm-granite/granite-4.2-8b-fp8` should wait on these measurements on this corpus: (1) v0.29.0 boot and peak VRAM at 16384 and, if memory allows, something above 16384, with `causal_conv1d` and `fla` present or the silent PyTorch fallback confirmed; (2) JSON or schema validity with `enable_thinking` false versus the card default of thinking on, including how often the trace hits the completion cap; (3) class accuracy and field F1 against the frozen Qwen3-8B or 8B-AWQ runs, not against IFEval; (4) context overflow, meaning how many contracts, merger agreements, corporate records, correspondence, and claims exceed 16384 tokens after this pipeline's own chunking. The card's 128K thinking advice cannot be met on one L4, so a quality drop from the short window is an empirical question, not a reason to pretend 262144 fits.
- Online FP8 quality versus bf16 for the 9B is also unmeasured. Larger official Qwen FP8 cards claim near-parity with the original; the 9B has no such official card. A bf16-versus-online-FP8 ablation belongs on the same documents if the L4 bf16 KV pool cannot even boot a useful context.
- Choosing Gemma 3 12B, Phi-4-mini, or a DeepSeek distill would be a new experiment. Nothing retrieved here settles those against this taxonomy.

### Gaps

- No corpus token-length histogram was computed in this pass, so the share of documents that overflow 16384 versus 32768 is unknown.
- No prior sandbox score table for Granite versus Qwen3-8B on these five classes was opened. The runbook exists; the result was not reviewed here.
- Chat-arena rank was not used. No arena snapshot was fetched, on purpose.
