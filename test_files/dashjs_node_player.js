const puppeteer = require('puppeteer');

const mpdUrl = process.env.MPD_URL || "http://localhost:8080/manifest.mpd";
const duration = parseInt(process.env.SESSION_DURATION) || 300;

(async () => {
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
                const url = "${mpdUrl}";
                const video = document.querySelector("#videoPlayer");
                const player = dashjs.MediaPlayer().create();
                
                // 1. LIGAR OS EVENTOS PRIMEIRO (Para nunca perder um erro!)
                player.on(dashjs.MediaPlayer.events.STREAM_INITIALIZED, () => console.log("browser_log: Stream Initialized"));
                player.on(dashjs.MediaPlayer.events.ERROR, (e) => console.log("browser_log: ERRO PLAYER: " + JSON.stringify(e)));
                player.on(dashjs.MediaPlayer.events.QUALITY_CHANGE_RENDERED, (e) => {
                    if (e.mediaType === 'video') {
                        console.log("browser_log: [EVENTO] >>> Qualidade alterada para indice: " + e.newQuality);
                    }
                });

                // 2. APLICAR CONFIGURACOES
                player.updateSettings({
                    'streaming': {
                        'abr': {
                            'ABRStrategy': 'abrThroughput', 
                            'initialBitrate': { 'audio': -1, 'video': 500 },
                            'autoSwitchBitrate': { 'video': true }
                        },
                        'fragmentRequestTimeout': 60000,
                        'manifestRequestTimeout': 10000,
                        'retryIntervals': {
                            'MediaSegment': 2000
                        },
                        'retryAttempts': {
                            'MediaSegment': 3
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
                        
                        const time = video.currentTime.toFixed(1);
                        const buffer = video.buffered.length > 0 ? video.buffered.end(0).toFixed(1) : 0;

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
                        
                        console.log("browser_log: [STATUS 5s] Tempo: " + time + "s | Frames: " + frames + " | Buffer: " + buffer + "s | Bitrate: " + bitrateString);
                    }
                }, 5000);

            </script>
        </body>
    </html>
    `;

    // --- REMOVI O FILTRO CEGO! AGORA VAMOS VER TUDO! ---
    page.on('console', msg => {
        const text = msg.text();
        if (text.startsWith('browser_log:')) {
            console.log(text.replace('browser_log: ', ''));
        } else {
            // Imprime erros nativos do Chrome
            console.log("[CHROME DEBUG] " + text); 
        }
    });
    
    // Captura erros fatais da página (ex: CDN bloqueada, erro de sintaxe)
    page.on('pageerror', err => {
        console.log("[CHROME FATAL ERROR] " + err.toString());
    });

    await page.setContent(htmlContent);
    await new Promise(r => setTimeout(r, duration * 1000));

    console.log("[CLIENT] Teste finalizado.");
    await browser.close();
})();