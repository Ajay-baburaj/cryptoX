#!/usr/bin/env bash
set -euo pipefail
GC=${GCLOUD:-gcloud}
PROJECT=cryptox-5a848
REGION=asia-south1
ZONE=asia-south1-a
SA=cryptox-engine@${PROJECT}.iam.gserviceaccount.com
if ! "$GC" iam service-accounts describe "$SA" --project="$PROJECT" >/dev/null 2>&1; then
  "$GC" iam service-accounts create cryptox-engine --display-name='CryptoX paper engine' --project="$PROJECT"
fi
"$GC" projects add-iam-policy-binding "$PROJECT" --member="serviceAccount:$SA" --role=roles/firebasecloudmessaging.admin --condition=None --quiet >/dev/null
if ! "$GC" compute networks describe cryptox-net --project="$PROJECT" >/dev/null 2>&1; then
  "$GC" compute networks create cryptox-net --subnet-mode=custom --project="$PROJECT" --quiet
fi
if ! "$GC" compute networks subnets describe cryptox-subnet --region="$REGION" --project="$PROJECT" >/dev/null 2>&1; then
  "$GC" compute networks subnets create cryptox-subnet --network=cryptox-net --range=10.40.0.0/24 --region="$REGION" --project="$PROJECT" --quiet
fi
if ! "$GC" compute firewall-rules describe cryptox-web --project="$PROJECT" >/dev/null 2>&1; then
  "$GC" compute firewall-rules create cryptox-web --network=cryptox-net --allow=tcp:80,tcp:443 --source-ranges=0.0.0.0/0 --target-tags=cryptox-web --project="$PROJECT" --quiet
fi
if ! "$GC" compute firewall-rules describe cryptox-iap-ssh --project="$PROJECT" >/dev/null 2>&1; then
  "$GC" compute firewall-rules create cryptox-iap-ssh --network=cryptox-net --allow=tcp:22 --source-ranges=35.235.240.0/20 --target-tags=cryptox-web --project="$PROJECT" --quiet
fi
if ! "$GC" compute addresses describe cryptox-ip --region="$REGION" --project="$PROJECT" >/dev/null 2>&1; then
  "$GC" compute addresses create cryptox-ip --region="$REGION" --project="$PROJECT" --quiet
fi
ADDRESS=$("$GC" compute addresses describe cryptox-ip --region="$REGION" --project="$PROJECT" --format='value(address)')
if ! "$GC" compute instances describe cryptox-bot --zone="$ZONE" --project="$PROJECT" >/dev/null 2>&1; then
  "$GC" compute instances create cryptox-bot --project="$PROJECT" --zone="$ZONE" --machine-type=e2-medium \
    --subnet=cryptox-subnet --address="$ADDRESS" --tags=cryptox-web \
    --image-family=debian-12 --image-project=debian-cloud --boot-disk-size=20GB --boot-disk-type=pd-balanced \
    --no-boot-disk-auto-delete --service-account="$SA" \
    --scopes=https://www.googleapis.com/auth/firebase.messaging \
    --shielded-secure-boot --labels=app=cryptox,mode=paper --quiet
fi
printf 'CryptoX dedicated IP: %s\n' "$ADDRESS"
