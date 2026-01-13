#!/bin/bash

# ================= CONFIGURAÇÕES =================
# Namespace do Kubernetes
NAMESPACE="nrprediger"

# Configurações do Slice de Vídeo (Slice 01)
SLICE_SST=1
SLICE_SD="000001"
DNN="slice01"
BANDWIDTH="1000M"  # Limite de banda (opcional, ex: "5M" para 5Mbps)

# Intervalo de IMSIs
# Começa no IMSI final ...003 (já que o 001 e 002 você usou para testes manuais)
START_ID=1
# Quantidade de clientes a criar
COUNT=6 

# Imagem do Player de Vídeo
APP_IMAGE="rambo1802/dash-node:latest"
# =================================================

echo "--- Iniciando Deploy de Clientes de Vídeo (Slice 01) ---"

for (( i=0; i<$COUNT; i++ ))
do
    # Calcula o ID atual e o sufixo (ex: 3 -> "03")
    CURRENT_ID=$(($START_ID + $i))
    SUFFIX=$(printf "%02d" $CURRENT_ID)
    
    # Monta o IMSI completo
    IMSI="9997000000000${SUFFIX}"
    
    # Nomes dos recursos K8s
    POD_NAME="ue-video-${SUFFIX}"
    CM_NAME="config-video-${SUFFIX}"

    echo ">>> Criando Cliente: $POD_NAME | IMSI: $IMSI | Slice: $SLICE_SD"

    # Gera o YAML e aplica diretamente no Cluster
    cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: ConfigMap
metadata:
  name: ${CM_NAME}
  namespace: ${NAMESPACE}
data:
  # Configuração da Torre (gNB)
  gnb.yaml: |
    mcc: '999'
    mnc: '70'
    nci: '0x0000000${SUFFIX}'
    idLength: 32
    tac: 1
    linkIp: '0.0.0.0'
    gtpIp: 'gnb'
    ngapIp: '0.0.0.0'
    name: 'gnb-${SUFFIX}'
    amfConfigs:
      - address: amf
        port: 38412
    slices:
      - sst: ${SLICE_SST}
        sd: '${SLICE_SD}'
    ignoreStreamIds: true
    gnbConnections:
      - name: gnb-n2
        protocol: sctp
        address: 0.0.0.0
        port: 38412
      - name: gnb-n3
        protocol: udp
        address: 0.0.0.0
        port: 2152

  # Configuração do Chip (UE)
  ue.yaml: |
    supi: 'imsi-${IMSI}'
    mcc: '999'
    mnc: '70'
    # SUCI Protection Scheme : 0 for Null-scheme, 1 for Profile A and 2 for Profile B
    protectionScheme: 0
    # Home Network Public Key for protecting with SUCI Profile A
    homeNetworkPublicKey: '5a8d38864820197c3394b92613b20b91633cbd897119273bf8e4a6f4eec0a650'
    # Home Network Public Key ID for protecting with SUCI Profile A
    homeNetworkPublicKeyId: 1
    # Routing Indicator
    routingIndicator: '0000'
    key: '465B5CE8B199B49FAA5F0A2EE238A6BC'
    op: 'E8ED289DEBA952E4283B54E88E6183CA'
    opType: 'OPC'
    amf: '8000'
    tunNetmask: '255.255.255.0'
    gnbSearchList:
      - 127.0.0.1
    # UAC Access Identities Configuration
    uacAic:
      mps: false
      mcs: false

    # UAC Access Control Class
    uacAcc:
      normalClass: 0
      class11: false
      class12: false
      class13: false
      class14: false
      class15: false
    sessions:
      - type: 'IPv4'
        apn: '${DNN}'
        dnn: '${DNN}'
        slice:
          sst: ${SLICE_SST}
          sd: ${SLICE_SD}
    configured-nssai:
      - sst: ${SLICE_SST}
        sd: ${SLICE_SD}
    default-nssai:
      - sst: ${SLICE_SST}
        sd: ${SLICE_SD}
    integrity:
      IA1: true
      IA2: true
      IA3: true
    ciphering:
      EA1: true
      EA2: true
      EA3: true
    integrityMaxRate:
      uplink: 'full'
      downlink: 'full'


---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: ${POD_NAME}
  namespace: ${NAMESPACE}
spec:
  replicas: 1
  selector:
    matchLabels:
      app: ${POD_NAME}
  template:
    metadata:
      labels:
        app: ${POD_NAME}
      annotations:
        # Limite de banda opcional (Calico)
        qos.projectcalico.org/ingressBandwidth: ${BANDWIDTH}
    spec:
      volumes:
        - name: config-volume
          configMap:
            name: ${CM_NAME}
        - name: dev-net-tun
          hostPath:
            path: /dev/net/tun
      containers:
        # 1. Container da Torre (gNB)
        - name: gnb
          image: free5gc/ueransim:latest
          securityContext:
            capabilities:
              add: ["NET_ADMIN"]
          env:
            - name: MY_POD_IP
              valueFrom:
                fieldRef:
                  fieldPath: status.podIP
          # Configura o IP do gNB dinamicamente na inicialização
          command: 
            - "/bin/bash"
            - "-c"
            - |
              cp /etc/ueransim/gnb.yaml config/gnb.yaml && \
              sed -i "s/gtpIp: 'gnb'/gtpIp: '\$MY_POD_IP'/g" config/gnb.yaml && \
              ./nr-gnb -c config/gnb.yaml
          volumeMounts:
            - name: config-volume
              mountPath: /etc/ueransim/gnb.yaml
              subPath: gnb.yaml
            - name: dev-net-tun
              mountPath: /dev/net/tun
        
        # 2. Container do Celular (UE)
        - name: ue
          image: free5gc/ueransim:latest
          securityContext:
            privileged: true
            capabilities:
              add: ["NET_ADMIN"]
          command: ["./nr-ue", "-c", "/etc/ueransim/ue.yaml"]
          volumeMounts:
            - name: config-volume
              mountPath: /etc/ueransim/ue.yaml
              subPath: ue.yaml
            - name: dev-net-tun
              mountPath: /dev/net/tun

        # 3. Container do Player de Vídeo (Aplicação)
        - name: dash-client
          image: ${APP_IMAGE}
          imagePullPolicy: IfNotPresent
          securityContext:
            capabilities:
              add: ["NET_ADMIN"]
          env:
            - name: MPD_URL
              value: "http://dash-server-service:8080/BBB_vod_2s/ftp.itec.aau.at/datasets/DASHDataset2014/BigBuckBunny/2sec/BigBuckBunny_2s_simple_2014_05_09.mpd"
            - name: SESSION_DURATION
              value: "300"
          command: ["/bin/sh", "-c"]
          args:
            - |
              echo "[INIT] Aguardando interface 5G (uesimtun0)..."
              # Loop de espera até o UE conectar e criar a interface de rede
              while ! ip link show uesimtun0 > /dev/null 2>&1; do sleep 1; done
              echo "[INIT] Interface uesimtun0 detectada!"

              echo "[INIT] Configurando rota para o servidor de vídeo..."
              # Descobre o IP do Service do Servidor de Vídeo
              SERVER_IP=\$(getent hosts dash-server-service | awk '{ print \$1 }')
              
              if [ -z "\$SERVER_IP" ]; then
                echo "[ERRO] Não foi possível resolver dash-server-service. Usando rota default..."
              else
                # Força o tráfego do vídeo a passar pela interface 5G
                ip route add \$SERVER_IP dev uesimtun0
                echo "[ROTA] Tráfego para \$SERVER_IP roteado via uesimtun0"
              fi
              
              echo "[INIT] Iniciando Player DASH..."
              node dashjs_node_player.js
EOF

done

echo "--- Concluído. Verifique os pods com: kubectl get pods -n ${NAMESPACE} ---"