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
            <video id="videoPlayer" controls muted></video>
            <script>
                const url = "${mpdUrl}";
                const video = document.querySelector("#videoPlayer");
                const player = dashjs.MediaPlayer().create();
                
                player.initialize(video, url, true);
                
                player.updateSettings({
                    'streaming': {
                        'abr': {
                            'autoSwitchBitrate': { 'video': true }
                        }
                    }
                });
                
                player.play();

                player.on(dashjs.MediaPlayer.events.STREAM_INITIALIZED, () => console.log("browser_log: Stream Initialized"));
                player.on(dashjs.MediaPlayer.events.ERROR, (e) => console.log("browser_log: ERRO PLAYER: " + JSON.stringify(e)));

                // --- VOLTEI COM O AVISO DE TROCA DE QUALIDADE ---
                player.on(dashjs.MediaPlayer.events.QUALITY_CHANGE_RENDERED, (e) => {
                    if (e.mediaType === 'video') {
                        console.log("browser_log: [EVENTO] >>> Qualidade alterada para indice: " + e.newQuality);
                    }
                });

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

    page.on('console', msg => {
        const text = msg.text();
        if (text.startsWith('browser_log:')) {
            console.log(text.replace('browser_log: ', ''));
        }
    });

    await page.setContent(htmlContent);
    await new Promise(r => setTimeout(r, duration * 1000));

    console.log("[CLIENT] Teste finalizado.");
    await browser.close();
})();