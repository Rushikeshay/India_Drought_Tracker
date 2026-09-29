# Oracle Cloud VM for India-WRIS groundwater

`indiawris.gov.in` only answers Indian IP addresses. A free Oracle Cloud VM in
Mumbai or Hyderabad runs `pipeline/sources/wris.py` every week and pushes the
results to this repo. Cost: $0 within Oracle's Always Free limits.

## 1. Create the Oracle account (about 15 min)

1. Sign up at https://www.oracle.com/cloud/free/.
2. **Home region: `India West (Mumbai)` or `India South (Hyderabad)`.** This can't be changed later, and Always Free VMs only run in the home region.
3. A credit or debit card is needed for identity checks. Always Free resources aren't charged.
4. **Upgrade to Pay As You Go** (Billing → Upgrade and Manage Payment). Always Free usage stays $0, but on a free-only account Oracle **reclaims VMs that sit idle for 7 days**, and this VM is idle most of the week. After upgrading, set a budget alert of ₹1 / $1 (Billing → Budgets) so you'd hear about any charge at all.

## 2. Create the VM (about 10 min)

Compute → Instances → Create instance:

- **Image:** Canonical Ubuntu 24.04.
- **Shape:** `VM.Standard.E2.1.Micro` (AMD, "Always Free-eligible"). The Ampere A1 shape is also free but often shows "out of capacity" in Indian regions. E2.1.Micro is enough.
- **Networking:** defaults (new VCN, public IPv4 address assigned).
- **SSH keys:** "Generate a key pair for me" → **download the private key** (for example `~/Downloads/ssh-key-*.key`).
- Create, then wait until the state is Running and copy the **Public IP address**.

## 3. Connect and run setup (about 10 min)

On your Mac:

```bash
chmod 600 ~/Downloads/ssh-key-*.key
ssh -i ~/Downloads/ssh-key-*.key ubuntu@<PUBLIC_IP>
```

On the VM:

```bash
curl -fsSL https://raw.githubusercontent.com/Rushikeshay/India_Drought_Tracker/main/deploy/oracle/setup.sh | bash
```

The script:
1. Installs packages and adds swap.
2. **Checks that WRIS is reachable.** If not, it stops. Tell Claude.
3. Prints a deploy key. Add it at GitHub → repo **Settings → Deploy keys → Add deploy key**, title `oracle-vm`, **tick "Allow write access"**, then press Enter on the VM.
4. Clones the repo, installs Python, runs the WRIS probe, and installs the weekly cron job (Sunday 03:00 IST).

Then start the first full pull, which takes 1–2 hours and keeps running if you disconnect:

```bash
nohup ~/India_Drought_Tracker/deploy/oracle/run_wris.sh >> ~/wris.log 2>&1 &
tail -f ~/wris.log      # Ctrl-C stops watching; the job keeps running
```

## Maintenance

- Logs: `~/wris.log` on the VM. Results: commits titled "WRIS groundwater update …" on GitHub.
- Run now: `~/India_Drought_Tracker/deploy/oracle/run_wris.sh`
- Test one state: `cd ~/India_Drought_Tracker && .venv/bin/python -m pipeline.sources.wris --states Maharashtra --max-districts 2`
- Security: the deploy key can write to this one repo only. If the VM is ever compromised, delete the key under Settings → Deploy keys.
