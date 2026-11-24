const { createWorker, MediaTypes } = require('mediasoup');

let worker = null;

async function createMediasoupWorker(config = {}) {
    const {
        rtcMinPort = 40000,
        rtcMaxPort = 49999,
    } = config;

    worker = await createWorker({
        logLevel: 'warn',
        rtcMinPort,
        rtcMaxPort,
    });

    worker.on('died', () => {
        console.error('Mediasoup worker died!');
        process.exit(1);
    });

    console.log(`Mediasoup worker started, pid: ${worker.pid}`);

    return worker;
}

async function createRouter(mediaCodecs) {
    if (!worker) {
        throw new Error('Mediasoup worker not initialized');
    }

    const router = await worker.createRouter({
        mediaCodecs,
    });

    return router;
}

async function createWebRtcTransport(router, config = {}) {
    const {
        maxIncomingBitrate = 1500000,
        initialAvailableOutgoingBitrate = 1000000,
    } = config;

    const transport = await router.createWebRtcTransport({
        maxIncomingBitrate,
        initialAvailableOutgoingBitrate,
        enableUdp: true,
        enableTcp: true,
        preferUdp: true,
        enableSctp: true,
    });

    return transport;
}

module.exports = {
    createMediasoupWorker,
    createRouter,
    createWebRtcTransport,
};
