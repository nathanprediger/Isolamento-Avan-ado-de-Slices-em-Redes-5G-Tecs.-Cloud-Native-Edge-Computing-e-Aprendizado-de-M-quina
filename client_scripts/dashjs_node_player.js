const puppeteer = require('puppeteer');

const mpdUrl = process.env.MPD_URL || "http://localhost:8080/manifest.mpd";
const duration = parseInt(process.env.SESSION_DURATION) || 300;

(async () => {
    const scriptStartTime = Date.now();  // ← NOVO: marca início do script
    
    console.log(`[CLIENT] Iniciando Player DASH (Com Eventos de Troca)...`);
    console.log(`[CLIENT] Alvo: ${mpdUrl}`);
    console.log(`[CLIENT] Duracao do teste: ${duration}s`);

    const browser = await puppeteer.launch({
        executablePath: process.env.PUPPETEER_EXECUTABLE_PATH || '/usr/bin/google-chrome-stable',
        args: [
            '--no-sandbox', 
            '--disable-setuid-sandbox',
            '--disable-dev-shm-usage',
            '--autoplay-policy=no-user-gesture-required',
            '--disable-web-security', 
            '--disable-features=IsolateOrigins,site-per-process'
        ]
    });

    const page = await browser.newPage();
    await page.setCacheEnabled(false);

    const htmlContent = `
    <!DOCTYPE html>
    <html>
        <head>
            <script src="https://cdn.dashjs.org/v4.7.4/dash.all.min.js"></script>
            <style>video { width: 640px; height: 360px; }</style>
        </head>
        <body>
            <video id="videoPlayer" controls muted loop></video>
            <script>
                const scriptStartTime = Date.now();  // ← NOVO: marca início no browser também
                const url = "${mpdUrl}";
                const video = document.querySelector("#videoPlayer");
                const player = dashjs.MediaPlayer().create();
                
                window.dashPlayer = player;
                window.videoElement = video;

                // 1. LIGAR OS EVENTOS PRIMEIRO (Para nunca perder um erro!)
                player.on(dashjs.MediaPlayer.events.STREAM_INITIALIZED, () => console.log("browser_log: Stream Initialized"));
                player.on(dashjs.MediaPlayer.events.ERROR, (e) => console.log("browser_log: ERRO PLAYER: " + JSON.stringify(e)));
                player.on(dashjs.MediaPlayer.events.QUALITY_CHANGE_RENDERED, (e) => {
                    if (e.mediaType === 'video') {
                        const elapsedSeconds = ((Date.now() - scriptStartTime) / 1000).toFixed(1);  // ← NOVO: tempo desde início do script
                        console.log("browser_log: [T+" + elapsedSeconds + "s] [EVENTO] >>> Qualidade alterada para indice: " + e.newQuality);
                    }
                });

                // 2. APLICAR CONFIGURACOES
                player.updateSettings({
                    'streaming': {
                        'abr': {
                            'ABRStrategy': 'abrDynamic', 
                            'initialBitrate': { 'audio': -1, 'video': 500 },
                            'autoSwitchBitrate': { 'video': true }
                        },
                        'buffer': {
                            'fastSwitchEnabled': true,       // Substitui chunks de baixa qualidade se a rede melhorar
                            'stableBufferTime': 15,          // Mantém o player com "fome" sondando a rede a cada 15s
                            'bufferTimeAtTopQuality': 20,    // Limite máximo absoluto do buffer
                            'bufferTimeAtTopQualityLongForm': 20,
                            'bufferToKeep': 20
                        },
                        'fragmentRequestTimeout': 600000,
                        'manifestRequestTimeout': 10000,
                        'retryIntervals': {
                            'MPD': 5000,          // Espera 5s antes de tentar de novo
                            'MediaSegment': 5000  // Espera 5s antes de tentar o pedaço de vídeo de novo
                        },
                        'retryAttempts': {
                            'MPD': 100,           // Tenta baixar o manifesto 50 vezes!
                            'MediaSegment': 100   // Tenta baixar o vídeo 50 vezes!
                        }
                    }
                });
                
                // 3. INICIAR O PLAYER
                player.initialize(video, url, true);
                player.play();

                // --- LOG A CADA 5 SEGUNDOS ---
                setInterval(() => {
                    if (video && player) {
                        let frames = 0;
                        if (video.getVideoPlaybackQuality) {
                            frames = video.getVideoPlaybackQuality().totalVideoFrames;
                        }
                        
                        const elapsedSeconds = ((Date.now() - scriptStartTime) / 1000).toFixed(1);  // ← NOVO: tempo desde início do script
                        // Pega o tempo atual da reprodução (o que o usuário está assistindo agora)
                        const currentTime = video.currentTime;

                        // Calcula quanto vídeo existe à frente do tempo atual
                        let bufferAhead = 0;
                        if (video.buffered.length > 0) {
                            // Usamos video.buffered.length - 1 para pegar o bloco mais recente baixado
                            bufferAhead = video.buffered.end(video.buffered.length - 1) - currentTime;
                            
                            // Proteção: garante que o buffer nunca dê número negativo por bugs de precisão do JS
                            if (bufferAhead < 0) bufferAhead = 0; 
                        }
                        const buffer = bufferAhead.toFixed(1);

                        let bitrateString = "N/A";
                        try {
                            if (typeof player.getQualityFor === 'function') {
                                const qIndex = player.getQualityFor("video");
                                const qList = player.getBitrateInfoListFor("video");
                                
                                if (qList && qList[qIndex]) {
                                    const bitrateKbps = (qList[qIndex].bitrate / 1000).toFixed(0);
                                    bitrateString = bitrateKbps + " kbps";
                                } else {
                                    bitrateString = "Index: " + qIndex;
                                }
                            }
                        } catch (e) {
                            bitrateString = "Erro: " + e.message;
                        }
                        
                        if (video.paused) {
                            bitrateString = "0 kbps";
                        }
                        
                        console.log("browser_log: [T+" + elapsedSeconds + "s] [STATUS 5s] Frames: " + frames + " | Buffer: " + buffer + "s | Bitrate: " + bitrateString);
                    }
                }, 5000);

            </script>
        </body>
    </html>
    `;

    page.on('console', msg => {
        const text = msg.text();
        if (text.startsWith('browser_log:')) {
            console.log(text.replace('browser_log: ', ''));
        } else {
            console.log("[CHROME DEBUG] " + text); 
        }
    });
    
    page.on('pageerror', err => {
        console.log("[CHROME FATAL ERROR] " + err.toString());
    });

    // --- API DE PAUSA/RETOMADA VIA SINAIS ---

    // Escuta o comando de PAUSAR (SIGUSR1)
    process.on('SIGUSR1', async () => {
        console.log("browser_log: [COMANDO] Sinal SIGUSR1 recebido. Pausando tráfego...");
        await page.evaluate(() => {
            if (window.dashPlayer && window.videoElement) {
                // 1. Zera o buffer alvo para que o Dash.js pare de baixar novos fragmentos IMEDIATAMENTE
                window.dashPlayer.updateSettings({
                    'streaming': { 'buffer': { 'stableBufferTime': 0, 'bufferTimeAtTopQuality': 0, 'bufferToKeep': 0 } }
                });
                // 2. Pausa o vídeo
                window.videoElement.pause();
            }
        });
    });

    // Escuta o comando de RETOMAR (SIGUSR2)
    process.on('SIGUSR2', async () => {
        console.log("browser_log: [COMANDO] Sinal SIGUSR2 recebido. Retomando tráfego...");
        await page.evaluate(() => {
            if (window.dashPlayer && window.videoElement) {
                // 1. Restaura as configurações de buffer originais para o Dash.js voltar a "ter fome"
                window.dashPlayer.updateSettings({
                    'streaming': { 'buffer': { 'stableBufferTime': 15, 'bufferTimeAtTopQuality': 20, 'bufferToKeep': 20 } }
                });
                // 2. Dá o play novamente
                window.videoElement.play();
            }
        });
    });

    await page.setContent(htmlContent);
    await new Promise(r => setTimeout(r, duration * 1000));

    console.log("[CLIENT] Teste finalizado.");
    await browser.close();
})();