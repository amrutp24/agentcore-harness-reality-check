# Shot list for the article

Console shots to capture before tearing down the Terraform stack.
Region: us-east-1, account `dev`. Crop out the account ID where visible.

1. **Harness detail page** — Bedrock AgentCore console → Harnesses →
   `harness_probe_tf`. Shows name, status READY, model, execution role.
   Use as the "the two calls work" illustration.

2. **The shadow memory resource** — AgentCore console → Memory →
   `harness_harness_probe_tf_9e75-...`. The resource nobody created.
   Caption: "I never made this."

3. **The shadow agent runtime** — AgentCore console → Agent runtimes →
   `harness_harness_probe_tf-...`. Same point, second resource.

4. **The money side-by-side** (the article's best image, build as one
   composite):
   - Left: terminal running
     `aws ... get-harness` output (or the boto3 snippet) showing
     `"memory": {"managedMemoryConfiguration": {"arn": ...}}`
   - Right: terminal running
     `terraform state show aws_bedrockagentcore_harness.probe`
     scrolled to where memory should be — and isn't.
   PowerShell commands (both from the repo root):
   ```powershell
   # right half:
   cd terraform; terraform state show aws_bedrockagentcore_harness.probe; cd ..
   # left half:
   .venv\Scripts\python -c "import boto3,json; s=boto3.Session(profile_name='dev',region_name='us-east-1'); c=s.client('bedrock-agentcore-control'); h=[x for x in c.list_harnesses()['harnesses'] if x['harnessName']=='harness_probe_tf'][0]; print(json.dumps(c.get_harness(harnessId=h['harnessId'])['harness']['memory'], indent=2, default=str))"
   ```

5. **Scaffold measurement run** — from the repo root:
   ```powershell
   .venv\Scripts\python scripts\02_measure_scaffold.py
   ```
   Targets the still-deployed `harness_probe_tf` by default (the original
   SDK harness is gone). Re-run costs ~1¢. Numbers may differ by a few
   tokens from NOTES.md (system prompt is byte-identical, so likely
   942/942/921/984 again).

6. **Clean plan lying politely** — `terraform plan` output ending in
   "No changes. Your infrastructure matches the configuration."
   Caption ties to the "a clean plan tells you everything is fine" line.

After all shots: `terraform destroy` in terraform/, then
`.venv\Scripts\python scripts\99_cleanup.py` to remove the leftover
SDK-probe IAM role.
