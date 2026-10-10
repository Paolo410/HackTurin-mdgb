#!/usr/bin/env bash
# Crea un "Thing" AWS IoT Core con certificato X.509 e policy.  Richiede AWS CLI configurata (aws configure).
#
#   ./aws/setup_thing.sh xw-001            aws/node-policy.json     # il nodo sull'UNO Q
#   ./aws/setup_thing.sh crosswalk-ingest  aws/ingest-policy.json   # il subscriber di backend
#
# Output: certs/<thing>.cert.pem, certs/<thing>.private.key, certs/AmazonRootCA1.pem + endpoint da usare in MQTT_HOST.
# I certificati sono credenziali: NON committarli su git.
set -euo pipefail

THING="${1:?nome del thing}"
POLICY_FILE="${2:?file policy json}"
POLICY_NAME="crosswalk-$(basename "$POLICY_FILE" .json)"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CERTS="$ROOT/certs"
mkdir -p "$CERTS"

REGION="$(aws configure get region)"
ACCOUNT="$(aws sts get-caller-identity --query Account --output text)"

aws iot create-thing --thing-name "$THING" >/dev/null 2>&1 || echo "thing $THING già esistente"

CERT_ARN="$(aws iot create-keys-and-certificate --set-as-active \
  --certificate-pem-outfile "$CERTS/$THING.cert.pem" \
  --public-key-outfile "$CERTS/$THING.public.key" \
  --private-key-outfile "$CERTS/$THING.private.key" \
  --query certificateArn --output text)"

TMP="$(mktemp)"
sed -e "s/REGION/$REGION/g" -e "s/ACCOUNT/$ACCOUNT/g" "$POLICY_FILE" > "$TMP"
aws iot create-policy --policy-name "$POLICY_NAME" --policy-document "file://$TMP" >/dev/null 2>&1 \
  || echo "policy $POLICY_NAME già esistente"
rm -f "$TMP"

aws iot attach-policy --policy-name "$POLICY_NAME" --target "$CERT_ARN"
aws iot attach-thing-principal --thing-name "$THING" --principal "$CERT_ARN"

[ -f "$CERTS/AmazonRootCA1.pem" ] || curl -sSf -o "$CERTS/AmazonRootCA1.pem" https://www.amazontrust.com/repository/AmazonRootCA1.pem

ENDPOINT="$(aws iot describe-endpoint --endpoint-type iot:Data-ATS --query endpointAddress --output text)"
cat <<EOF

OK: thing "$THING" pronto (regione $REGION).
Variabili da usare:
  export MQTT_HOST=$ENDPOINT
  export MQTT_PORT=8883            # oppure 443 se la rete blocca la 8883
  export MQTT_TLS=1
  export MQTT_CA=$CERTS/AmazonRootCA1.pem
  export MQTT_CERT=$CERTS/$THING.cert.pem
  export MQTT_KEY=$CERTS/$THING.private.key
EOF
