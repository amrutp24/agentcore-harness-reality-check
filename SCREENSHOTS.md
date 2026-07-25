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
   PowerShell commands:
   ```powershell
   cd terraform
   terraform state show aws_bedrockagentcore_harness.probe
   # and for the left half:
   ..\.venv\Scripts\python -c "import boto3,json; s=boto3.Session(profile_name='dev',region_name='us-east-1'); c=s.client('bedrock-agentcore-control'); h=[x for x in c.list_harnesses()['harnesses'] if x['harnessName']=='harness_probe_tf'][0]; print(json.dumps(c.get_harness(harnessId=h['harnessId'])['harness']['memory'], indent=2, default=str))"
   ```

5. **Scaffold measurement run** — terminal output of
   `.venv\Scripts\python scripts\02_measure_scaffold.py` showing the
   942/921/984 rows. (Re-run costs ~1¢; needs the SDK harness recreated
   first via scripts/01, or just screenshot the table from NOTES.md data
   in a fresh run against harness_probe_tf by editing HARNESS_NAME.)

6. **Clean plan lying politely** — `terraform plan` output ending in
   "No changes. Your infrastructure matches the configuration."
   Caption ties to the "a clean plan tells you everything is fine" line.

After all shots: `terraform destroy` in terraform/, then
`.venv\Scripts\python scripts\99_cleanup.py` to remove the leftover
SDK-probe IAM role.
