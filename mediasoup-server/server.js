const { createServer } = require('http');
const express = require('express');
const cors = require('cors');
const { v4: uuidv4 } = require('uuid');

const app = express();
app.use(cors());
app.use(express.json({ limit: '10mb' }));

const httpServer = createServer(app);

const rooms = new Map();
const peers = new Map();

let pendingMessages = new Map();

const MEDIASOUP_CONFIG = {
    worker: {
        rtcMinPort: 40000,
        rtcMaxPort: 49999,
    },
    router: {
        mediaCodecs: [
            { kind: 'audio', mimeType: 'audio/opus', clockRate: 48000, channels: 2 },
            { kind: 'video', mimeType: 'video/VP8', clockRate: 90000 },
            { kind: 'video', mimeType: 'video/VP9', clockRate: 90000 },
            { kind: 'video', mimeType: 'video/H264', clockRate: 90000, parameters: { 'packetization-mode': 1, 'profile-level-id': '42e01f' } },
        ],
    },
    webRtcTransport: {
        maxIncomingBitrate: 1500000,
        initialAvailableOutgoingBitrate: 1000000,
    },
};

let worker;
let mediaCodecs;

async function initializeMediasoup() {
    try {
        const { createWorker } = require('mediasoup');
        worker = await createWorker({
            logLevel: 'warn',
            rtcMinPort: MEDIASOUP_CONFIG.worker.rtcMinPort,
            rtcMaxPort: MEDIASOUP_CONFIG.worker.rtcMaxPort,
        });
        mediaCodecs = MEDIASOUP_CONFIG.router.mediaCodecs;
        
        worker.on('died', () => {
            console.error('Mediasoup worker died!');
            process.exit(1);
        });
        
        console.log(`Mediasoup worker started, pid: ${worker.pid}`);
    } catch (error) {
        console.error('Failed to initialize mediasoup worker:', error);
        process.exit(1);
    }
}

function getRoom(roomId) {
    return rooms.get(roomId) || null;
}

async function createRoom(roomId) {
    if (rooms.has(roomId)) {
        return rooms.get(roomId);
    }

    const router = await worker.createRouter({ mediaCodecs });
    
    const room = {
        id: roomId,
        router,
        peers: new Map(),
        createdAt: Date.now(),
    };

    pendingMessages.set(roomId, []);
    rooms.set(roomId, room);
    console.log(`Room ${roomId} created`);
    return room;
}

async function createPeerTransport(peerId, room) {
    const transport = await room.router.createWebRtcTransport({
        ...MEDIASOUP_CONFIG.webRtcTransport,
    });

    transport.on('dtlsstatechange', (dtlsState) => {
        if (dtlsState === 'failed' || dtlsState === 'closed') {
            console.log(`Transport ${transport.id} dtls state: ${dtlsState}`);
        }
    });

    transport.on('close', () => {
        console.log(`Transport ${transport.id} closed`);
    });

    const peer = {
        id: peerId,
        room,
        transport,
        producers: new Map(),
        consumers: new Map(),
        joined: false,
        displayName: 'Guest',
        isHost: false,
        ws: null,
    };

    room.peers.set(peerId, peer);
    peers.set(peerId, peer);

    return peer;
}

function broadcastToRoom(roomId, excludePeerId, message) {
    const room = getRoom(roomId);
    if (!room) return;
    
    const msgStr = JSON.stringify(message);
    
    room.peers.forEach((p) => {
        if (p.id !== excludePeerId && p.pendingMessages) {
            p.pendingMessages.push(msgStr);
        }
    });
    
    const roomPending = pendingMessages.get(roomId) || [];
    roomPending.push({ exclude: excludePeerId, message });
    pendingMessages.set(roomId, roomPending);
}

function getPendingMessages(roomId, peerId, lastIndex = 0) {
    const room = getRoom(roomId);
    if (!room) return { messages: [], index: 0 };
    
    const peer = room.peers.get(peerId);
    if (peer && peer.pendingMessages) {
        const messages = peer.pendingMessages.slice(lastIndex).map(m => JSON.parse(m));
        peer.pendingMessages = peer.pendingMessages.slice(lastIndex);
        return { 
            messages, 
            index: lastIndex + messages.length,
            participants: Array.from(room.peers.values()).filter(p => p.joined).map(p => ({
                id: p.id, displayName: p.displayName, isHost: p.isHost
            }))
        };
    }
    
    return { messages: [], index: lastIndex, participants: [] };
}

app.post('/api/room/:roomId/join', async (req, res) => {
    try {
        const { roomId } = req.params;
        const { peerId, displayName, isHost } = req.body;
        
        if (!peerId) {
            return res.status(400).json({ error: 'peerId required' });
        }
        
        let room = getRoom(roomId);
        if (!room) {
            room = await createRoom(roomId);
        }
        
        let peer = room.peers.get(peerId);
        if (!peer) {
            peer = await createPeerTransport(peerId, room);
        }
        
        peer.joined = true;
        peer.displayName = displayName || 'Guest';
        peer.isHost = isHost || false;
        peer.pendingMessages = [];
        
        const existingProducers = [];
        room.peers.forEach((p) => {
            if (p.id !== peerId && p.joined) {
                p.producers.forEach((producer) => {
                    existingProducers.push({
                        producerId: producer.id,
                        peerId: p.id,
                        kind: producer.kind,
                        displayName: p.displayName,
                    });
                });
            }
        });
        
        broadcastToRoom(roomId, peerId, {
            type: 'peer-joined',
            peerId,
            displayName: peer.displayName,
            isHost: peer.isHost,
        });
        
        res.json({
            success: true,
            transport: {
                id: peer.transport.id,
                iceCandidates: peer.transport.iceCandidates,
                iceParameters: peer.transport.iceParameters,
                dtlsParameters: peer.transport.dtlsParameters,
            },
            router: {
                rtpCapabilities: room.router.rtpCapabilities,
            },
            existingProducers,
            participants: Array.from(room.peers.values()).filter(p => p.joined).map(p => ({
                id: p.id, displayName: p.displayName, isHost: p.isHost
            })),
        });
    } catch (error) {
        console.error('Join error:', error);
        res.status(500).json({ error: error.message });
    }
});

app.post('/api/transport/:transportId/connect', async (req, res) => {
    try {
        const { transportId } = req.params;
        const { dtlsParameters } = req.body;
        
        let foundTransport = null;
        for (const room of rooms.values()) {
            for (const peer of room.peers.values()) {
                if (peer.transport.id === transportId) {
                    foundTransport = peer.transport;
                    break;
                }
            }
            if (foundTransport) break;
        }
        
        if (!foundTransport) {
            return res.status(404).json({ error: 'Transport not found' });
        }
        
        await foundTransport.connect({ dtlsParameters });
        res.json({ success: true });
    } catch (error) {
        console.error('Connect error:', error);
        res.status(500).json({ error: error.message });
    }
});

app.post('/api/transport/:transportId/produce', async (req, res) => {
    try {
        const { transportId } = req.params;
        const { peerId, kind, rtpParameters } = req.body;
        
        let foundPeer = null;
        for (const room of rooms.values()) {
            const peer = room.peers.get(peerId);
            if (peer && peer.transport.id === transportId) {
                foundPeer = peer;
                break;
            }
        }
        
        if (!foundPeer) {
            return res.status(404).json({ error: 'Peer not found' });
        }
        
        const producer = await foundPeer.transport.produce({
            kind,
            rtpParameters,
        });
        
        foundPeer.producers.set(producer.id, producer);
        
        producer.on('score', (score) => {
            broadcastToRoom(foundPeer.room.id, peerId, {
                type: 'producer-score',
                producerId: producer.id,
                score,
            });
        });
        
        broadcastToRoom(foundPeer.room.id, peerId, {
            type: 'new-producer',
            producerId: producer.id,
            peerId,
            kind,
            displayName: foundPeer.displayName,
        });
        
        res.json({ success: true, producerId: producer.id });
    } catch (error) {
        console.error('Produce error:', error);
        res.status(500).json({ error: error.message });
    }
});

app.post('/api/transport/:transportId/consume', async (req, res) => {
    try {
        const { transportId } = req.params;
        const { peerId, remotePeerId, producerId, rtpCapabilities } = req.body;
        
        let consumingPeer = null;
        let remotePeer = null;
        
        for (const room of rooms.values()) {
            const peer = room.peers.get(peerId);
            if (peer && peer.transport.id === transportId) {
                consumingPeer = peer;
            }
            const remote = room.peers.get(remotePeerId);
            if (remote && remote.id === remotePeerId) {
                remotePeer = remote;
            }
            if (consumingPeer && remotePeer) break;
        }
        
        if (!consumingPeer || !remotePeer) {
            return res.status(404).json({ error: 'Peer not found' });
        }
        
        const remoteProducer = remotePeer.producers.get(producerId);
        if (!remoteProducer) {
            return res.status(404).json({ error: 'Producer not found' });
        }
        
        const consumer = await consumingPeer.transport.consume({
            producerId,
            rtpCapabilities,
            paused: false,
        });
        
        consumingPeer.consumers.set(consumer.id, consumer);
        
        consumer.on('transportclose', () => {
            consumingPeer.consumers.delete(consumer.id);
        });
        
        res.json({
            success: true,
            consumerId: consumer.id,
            producerId,
            kind: consumer.kind,
            rtpParameters: consumer.rtpParameters,
        });
    } catch (error) {
        console.error('Consume error:', error);
        res.status(500).json({ error: error.message });
    }
});

app.post('/api/peer/:peerId/resume', async (req, res) => {
    try {
        const { peerId } = req.params;
        const { consumerId } = req.body;
        
        let foundPeer = null;
        for (const room of rooms.values()) {
            const peer = room.peers.get(peerId);
            if (peer) {
                foundPeer = peer;
                break;
            }
        }
        
        if (!foundPeer) {
            return res.status(404).json({ error: 'Peer not found' });
        }
        
        const consumer = foundPeer.consumers.get(consumerId);
        if (consumer) {
            await consumer.resume();
        }
        
        res.json({ success: true });
    } catch (error) {
        console.error('Resume error:', error);
        res.status(500).json({ error: error.message });
    }
});

app.post('/api/peer/:peerId/leave', async (req, res) => {
    try {
        const { peerId } = req.params;
        
        let roomId = null;
        for (const [rid, room] of rooms) {
            if (room.peers.has(peerId)) {
                roomId = rid;
                break;
            }
        }
        
        if (roomId) {
            handlePeerLeave(peerId, roomId);
        }
        
        res.json({ success: true });
    } catch (error) {
        console.error('Leave error:', error);
        res.status(500).json({ error: error.message });
    }
});

app.post('/api/room/:roomId/broadcast', async (req, res) => {
    try {
        const { roomId } = req.params;
        const { peerId, message } = req.body;
        
        broadcastToRoom(roomId, peerId, message);
        res.json({ success: true });
    } catch (error) {
        console.error('Broadcast error:', error);
        res.status(500).json({ error: error.message });
    }
});

app.get('/api/room/:roomId/poll/:peerId', async (req, res) => {
    const { roomId, peerId } = req.params;
    const lastIndex = parseInt(req.query.lastIndex) || 0;
    
    try {
        const result = getPendingMessages(roomId, peerId, lastIndex);
        
        setTimeout(() => {
            res.json(result);
        }, 500);
    } catch (error) {
        console.error('Poll error:', error);
        res.status(500).json({ error: error.message });
    }
});

app.get('/api/room/:roomId/status', async (req, res) => {
    const { roomId } = req.params;
    const room = getRoom(roomId);
    
    if (!room) {
        return res.json({ exists: false, participantCount: 0 });
    }
    
    res.json({
        exists: true,
        participantCount: room.peers.size,
        activeCount: Array.from(room.peers.values()).filter(p => p.joined).length,
    });
});

app.post('/api/room/:roomId/host-action', async (req, res) => {
    try {
        const { roomId } = req.params;
        const { peerId, action, data } = req.body;
        
        const room = getRoom(roomId);
        if (!room) {
            return res.status(404).json({ error: 'Room not found' });
        }
        
        const peer = room.peers.get(peerId);
        if (!peer || !peer.isHost) {
            return res.status(403).json({ error: 'Only host can perform this action' });
        }
        
        broadcastToRoom(roomId, null, {
            type: 'host-action',
            action,
            data,
            fromPeerId: peerId,
            fromPeerName: peer.displayName,
            timestamp: Date.now(),
        });
        
        if (action === 'remove-participant' && data?.targetPeerId) {
            handlePeerLeave(data.targetPeerId, roomId);
        }
        
        res.json({ success: true });
    } catch (error) {
        console.error('Host action error:', error);
        res.status(500).json({ error: error.message });
    }
});

app.post('/api/room/:roomId/chat', async (req, res) => {
    try {
        const { roomId } = req.params;
        const { peerId, message } = req.body;
        
        const room = getRoom(roomId);
        if (!room) {
            return res.status(404).json({ error: 'Room not found' });
        }
        
        const peer = room.peers.get(peerId);
        
        broadcastToRoom(roomId, peerId, {
            type: 'chat-message',
            peerId,
            displayName: peer?.displayName || 'Guest',
            message,
            timestamp: Date.now(),
        });
        
        res.json({ success: true });
    } catch (error) {
        console.error('Chat error:', error);
        res.status(500).json({ error: error.message });
    }
});

app.get('/health', (req, res) => {
    res.json({
        status: 'healthy',
        rooms: rooms.size,
        peers: peers.size,
        uptime: process.uptime(),
    });
});

async function handlePeerLeave(peerId, roomId) {
    const room = getRoom(roomId);
    if (!room) return;

    const peer = room.peers.get(peerId);
    if (!peer) return;

    peer.producers.forEach((producer) => producer.close());
    peer.consumers.forEach((consumer) => consumer.close());
    peer.transport.close();

    room.peers.delete(peerId);
    peers.delete(peerId);

    broadcastToRoom(roomId, peerId, { type: 'peer-left', peerId });

    console.log(`Peer ${peerId} left room ${roomId}`);

    if (room.peers.size === 0) {
        setTimeout(() => {
            const currentRoom = getRoom(roomId);
            if (currentRoom && currentRoom.peers.size === 0) {
                currentRoom.router.close();
                rooms.delete(roomId);
                pendingMessages.delete(roomId);
                console.log(`Room ${roomId} deleted (empty)`);
            }
        }, 30000);
    }
}

const PORT = process.env.MEDIASOUP_PORT || 3001;

async function startServer() {
    await initializeMediasoup();
    
    httpServer.listen(PORT, () => {
        console.log(`Mediasoup SFU server running on port ${PORT}`);
        console.log(`API base URL: http://localhost:${PORT}/api/`);
        console.log(`Health check: http://localhost:${PORT}/health`);
    });
}

startServer().catch(console.error);

process.on('SIGINT', async () => {
    console.log('\nShutting down...');
    for (const [roomId, room] of rooms) {
        room.peers.forEach((peer) => {
            peer.producers.forEach((p) => p.close());
            peer.consumers.forEach((c) => c.close());
            peer.transport.close();
        });
        await room.router.close();
    }
    process.exit(0);
});
