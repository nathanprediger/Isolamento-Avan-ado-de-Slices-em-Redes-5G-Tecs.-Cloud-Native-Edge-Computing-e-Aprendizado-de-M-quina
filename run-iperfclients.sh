#!/bin/bash

# ================= CONFIGURAÇÕES =================
NAMESPACE="nrprediger"
START_ID=7
COUNT=3
TARGET="iperf01"
PORT="5001"
BANDWIDTH="50M"
DURATION="600"
# =================================================

echo "--- Iniciando Ataque Distribuído (UDP Flood) ---"

for (( i=0; i<$COUNT; i++ ))
do
    CURRENT_ID=$(($START_ID + $i))
    SUFFIX=$(printf "%02d" $CURRENT_ID)
    
    DEPLOY_NAME="ue-iperf-${SUFFIX}"

    # Pega o nome completo do pod
    POD_NAME=$(kubectl get pods -n ${NAMESPACE} -l app=${DEPLOY_NAME} -o jsonpath="{.items[0].metadata.name}")

    if [ -z "$POD_NAME" ]; then
        echo "[ERRO] Pod não encontrado para ${DEPLOY_NAME}"
        continue
    fi

    echo ">>> Disparando iPerf no container 'iperf-client' do pod: $POD_NAME"

    # --- CORREÇÃO: Adicionado '-c iperf-client' ---
    kubectl exec -n ${NAMESPACE} ${POD_NAME} -c iperf-client -- \
        sh -c "nohup iperf -c ${TARGET} -p ${PORT} -u -b ${BANDWIDTH} -t ${DURATION} -i 10 > /tmp/iperf.log 2>&1 &" &

done

echo "--- Ataque iniciado! ---"
echo "Verifique com: kubectl exec -it ${POD_NAME} -n ${NAMESPACE} -c iperf-client -- ps aux"