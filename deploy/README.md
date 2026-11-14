# CryptoX deployment

This deployment belongs only to GCP/Firebase project `cryptox-5a848`. It does not use Nifty's VM or project.

## Layout

- Firebase Hosting site: `cryptox-5a848`, public URL `https://cryptox-5a848.web.app`.
- Dedicated VM: `cryptox-bot`, zone `asia-south1-a`, e2-medium, retained 20 GB balanced persistent disk.
- Dedicated custom VPC/subnet, reserved regional external IP. Public ports 80/443; SSH only through IAP.
- Caddy terminates HTTPS and proxies to Python on loopback port 8000.
- `cryptox.service` runs as unprivileged user `cryptox`, restarts on failure and boots automatically.
- `/opt/cryptox/data/paper` stores strategy state, trade history, session secret and browser registrations. Keep it on updates. Do not run multiple copies of the cloud engine.
- Attached `cryptox-engine` service account has FCM API permissions in this project, without a downloaded service-account key.
- Hosted frontend uses short-lived Firebase ID tokens with refresh; backend verifies identity and the email allowlist. CORS allows only CryptoX Hosting origins. Local dashboard retains cookie login.

## Provision and publish

`GCLOUD=/path/to/gcloud bash deploy/provision.sh` creates the dedicated resources. Billing must already be linked and the Compute, IAP, IAM and FCM APIs enabled.

Upload a code-only archive to `/tmp/cryptox.tgz`, then run `sudo bash /tmp/install_vm.sh API_HOST` (copy `deploy/install_vm.sh` to that path first). The installer preserves existing state, updates the venv and restarts the service. It is for the dedicated CryptoX VM only.

Build and deploy frontend:

```sh
.venv/bin/python scripts/build_hosted.py --api-base https://API_HOST
npx -y firebase-tools@latest deploy --only hosting --project cryptox-5a848
```

Use `gcloud compute ssh cryptox-bot --project=cryptox-5a848 --zone=asia-south1-a --tunnel-through-iap` for maintenance. Then `sudo systemctl status cryptox` and `sudo journalctl -u cryptox -n 100`.

The dashboard is paper trading only. A new cloud installation starts an independent paper account unless state is explicitly migrated. Localhost notification registrations do not transfer to the hosted origin; enable notifications after signing in on the hosted dashboard.

VM, disk and IP incur ongoing cloud charges. The retained boot disk protects against automatic deletion with the VM; it is not an off-machine backup. Do not delete it without exporting needed paper history.
