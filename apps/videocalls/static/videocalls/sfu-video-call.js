const SFUVideoCall = {
    config: {
        roomCode: null,
        roomName: null,
        isHost: false,
        userName: '',
        userEmail: '',
        userId: null,
        sessionId: null,
        apiBaseUrl: '/videocalls/api/',
        sfuServerUrl: 'http://localhost:3001',
        mediasoupEnabled: true,
        device: null,
        rtpCapabilities: null,
        pollInterval: 300,
    },

    state: {
        localStream: null,
        processedStream: null,
        screenStream: null,
        producers: new Map(),
        consumers: new Map(),
        sendTransport: null,
        recvTransport: null,
        isRecording: false,
        isScreenSharing: false,
        isAudioEnabled: true,
        isVideoEnabled: true,
        isNoiseCancellationEnabled: false,
        callStartTime: null,
        chatMessages: [],
        participants: new Map(),
        connected: false,
        pollTimer: null,
        lastPollIndex: 0,
        transportCreated: false,
        audioContext: null,
        noiseGainNode: null,
        noiseAnalyser: null,
    },

    init: async function(config) {
        Object.assign(this.config, config);
        this.config.sessionId = this.generateSessionId();
        this.config.device = new mediasoupClient.Device();

        await this.loadConfig();
        this.bindEvents();
    },

    loadConfig: async function() {
        try {
            const response = await fetch('/videocalls/api/config/');
            const data = await response.json();

            if (data.success) {
                if (data.config.mediasoupEnabled !== undefined) {
                    this.config.mediasoupEnabled = data.config.mediasoupEnabled;
                }
                if (data.config.mediasoupWsUrl) {
                    this.config.sfuServerUrl = data.config.mediasoupWsUrl.replace('ws://', 'http://').replace('wss://', 'https://');
                }
                if (data.config.maxParticipants) {
                    this.config.maxParticipants = data.config.maxParticipants;
                }
                if (data.config.pollInterval) {
                    this.config.pollInterval = data.config.pollInterval;
                }
                console.log('SFU Config loaded:', {
                    mediasoupEnabled: this.config.mediasoupEnabled,
                    sfuServerUrl: this.config.sfuServerUrl,
                    pollInterval: this.config.pollInterval,
                });
            }
        } catch (error) {
            console.warn('Failed to load config, using defaults:', error);
        }
    },

    generateSessionId: function() {
        return 'sess_' + Math.random().toString(36).substr(2, 9) + Date.now().toString(36);
    },

    getCsrfToken: function() {
        return document.querySelector('meta[name="csrf-token"]')?.content ||
               document.querySelector('input[name="csrfmiddlewaretoken"]')?.value || '';
    },

    bindEvents: function() {
        document.addEventListener('visibilitychange', () => {
            if (document.visibilityState === 'visible' && this.state.connected) {
                this.startPolling();
            } else {
                this.stopPolling();
            }
        });

        window.addEventListener('beforeunload', () => {
            this.cleanup();
        });
    },

    async initLocalStream(videoConstraints = true, audioConstraints = true) {
        try {
            const constraints = {
                video: videoConstraints ? {
                    width: { ideal: 1280 },
                    height: { ideal: 720 },
                    facingMode: 'user',
                    frameRate: { ideal: 30, min: 15 },
                    videoLatency: 0
                } : false,
                audio: audioConstraints ? {
                    echoCancellation: false,
                    noiseSuppression: false,
                    autoGainControl: true,
                    latency: 0
                } : false
            };

            this.state.localStream = await navigator.mediaDevices.getUserMedia(constraints);
            
            if (this.state.localStream.getVideoTracks().length > 0) {
                this.state.localStream.getVideoTracks().forEach(track => {
                    track.applyConstraints({
                        width: { ideal: 1280 },
                        height: { ideal: 720 },
                        frameRate: { ideal: 30, min: 15 }
                    }).catch(() => {});
                });
            }
            
            this.setupNoiseCancellation();
            
            return this.state.localStream;
        } catch (error) {
            console.error('Error accessing media devices:', error);
            throw error;
        }
    },

    setupNoiseCancellation: function() {
        try {
            this.state.audioContext = new (window.AudioContext || window.webkitAudioContext)();
            const source = this.state.audioContext.createMediaStreamSource(this.state.localStream);
            
            this.state.noiseAnalyser = this.state.audioContext.createAnalyser();
            this.state.noiseAnalyser.fftSize = 256;
            
            const noiseGate = this.createNoiseGate();
            
            this.state.noiseGainNode = this.state.audioContext.createGain();
            this.state.noiseGainNode.gain.value = 1;
            
            source.connect(noiseGate);
            noiseGate.connect(this.state.noiseGainNode);
            this.state.noiseGainNode.connect(this.state.audioContext.destination);
            
            this.applyNoiseSuppressionFilters();
            
        } catch (error) {
            console.warn('Noise cancellation setup failed:', error);
        }
    },

    createNoiseGate: function() {
        const context = this.state.audioContext;
        const gate = context.createDynamicsCompressor();
        
        gate.threshold.value = -50;
        gate.knee.value = 10;
        gate.ratio.value = 20;
        gate.attack.value = 0.001;
        gate.release.value = 0.1;
        
        return gate;
    },

    applyNoiseSuppressionFilters: function() {
        if (!this.state.audioContext || !this.state.localStream) return;
        
        try {
            const source = this.state.audioContext.createMediaStreamSource(this.state.localStream);
            const filter = this.state.audioContext.createBiquadFilter();
            
            filter.type = 'lowpass';
            filter.frequency.value = 8000;
            filter.Q.value = 1;
            
            const gain = this.state.audioContext.createGain();
            gain.gain.value = 1;
            
            source.connect(filter);
            filter.connect(gain);
            gain.connect(this.state.audioContext.destination);
            
            this.state.audioFilter = filter;
            this.state.audioGain = gain;
            
        } catch (error) {
            console.warn('Advanced noise suppression setup failed:', error);
        }
    },

    enableNoiseCancellation: function() {
        this.state.isNoiseCancellationEnabled = true;
        
        if (this.state.audioFilter) {
            this.state.audioFilter.frequency.value = 8000;
        }
        
        const btn = document.getElementById('noiseCancelBtn');
        if (btn) {
            btn.classList.add('active');
        }
        
        this.showNotification('Noise cancellation enabled', 'info');
    },

    disableNoiseCancellation: function() {
        this.state.isNoiseCancellationEnabled = false;
        
        if (this.state.audioFilter) {
            this.state.audioFilter.frequency.value = 20000;
        }
        
        const btn = document.getElementById('noiseCancelBtn');
        if (btn) {
            btn.classList.remove('active');
        }
        
        this.showNotification('Noise cancellation disabled', 'info');
    },

    toggleNoiseCancellation: function() {
        if (this.state.isNoiseCancellationEnabled) {
            this.disableNoiseCancellation();
        } else {
            this.enableNoiseCancellation();
        }
    },

    async initScreenShare() {
        try {
            this.state.screenStream = await navigator.mediaDevices.getDisplayMedia({
                video: { cursor: 'always', displaySurface: 'monitor' },
                audio: true
            });

            const screenTrack = this.state.screenStream.getVideoTracks()[0];
            screenTrack.onended = () => {
                this.stopScreenShare();
            };

            return this.state.screenStream;
        } catch (error) {
            console.error('Error starting screen share:', error);
            throw error;
        }
    },

    async joinRoom() {
        try {
            const response = await fetch(this.config.apiBaseUrl + 'join/', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this.getCsrfToken()
                },
                body: JSON.stringify({
                    room_code: this.config.roomCode,
                    session_id: this.config.sessionId,
                    display_name: this.config.userName || this.config.userEmail || 'Guest'
                })
            });

            const data = await response.json();

            if (data.success) {
                this.updateConnectionStatus('connected');
                this.updateParticipantsList(data.room?.participants || []);
                await this.connectToSFU();
            }

            return data;
        } catch (error) {
            console.error('Error joining room:', error);
            this.updateConnectionStatus('disconnected');
            throw error;
        }
    },

    async sfuRequest(endpoint, method = 'GET', body = null) {
        const url = `${this.config.sfuServerUrl}/api${endpoint}`;
        
        try {
            const options = {
                method,
                headers: {
                    'Content-Type': 'application/json',
                },
            };
            
            if (body) {
                options.body = JSON.stringify(body);
            }
            
            const response = await fetch(url, options);
            const data = await response.json();
            
            if (!response.ok) {
                throw new Error(data.error || 'SFU request failed');
            }
            
            return data;
        } catch (error) {
            console.error(`SFU request error (${endpoint}):`, error);
            throw error;
        }
    },

    async connectToSFU() {
        if (!this.config.mediasoupEnabled) {
            console.log('SFU disabled, using P2P mode');
            return;
        }

        try {
            this.updateConnectionStatus('connecting');
            
            const joinData = await this.sfuRequest(`/room/${this.config.roomCode}/join`, 'POST', {
                peerId: this.config.sessionId,
                displayName: this.config.userName || 'Guest',
                isHost: this.config.isHost,
            });

            await this.config.device.load({ routerRtpCapabilities: joinData.router.rtpCapabilities });

            await this.createSendTransport(joinData.transport);

            joinData.existingProducers?.forEach(producerInfo => {
                this.consumeProducer(producerInfo);
            });

            joinData.participants?.forEach(peer => {
                if (peer.id !== this.config.sessionId) {
                    this.addParticipant(peer);
                }
            });

            this.updateParticipantsList(joinData.participants || []);
            this.state.connected = true;
            this.updateConnectionStatus('connected');
            
            this.startPolling();

        } catch (error) {
            console.error('Error connecting to SFU:', error);
            this.state.connected = false;
            this.updateConnectionStatus('failed');
        }
    },

    startPolling: function() {
        if (this.state.pollTimer) return;
        
        this.state.pollTimer = setInterval(async () => {
            await this.pollMessages();
        }, this.config.pollInterval);
    },

    stopPolling: function() {
        if (this.state.pollTimer) {
            clearInterval(this.state.pollTimer);
            this.state.pollTimer = null;
        }
    },

    pollMessages: async function() {
        try {
            const data = await this.sfuRequest(
                `/room/${this.config.roomCode}/poll/${this.config.sessionId}?lastIndex=${this.state.lastPollIndex}`
            );

            if (data.messages && data.messages.length > 0) {
                for (const msg of data.messages) {
                    await this.handleSFUMessage(msg);
                    this.state.lastPollIndex++;
                }
            }

            if (data.participants) {
                this.updateParticipantsList(data.participants);
            }
        } catch (error) {
            console.error('Poll error:', error);
        }
    },

    async handleSFUMessage(data) {
        switch (data.type) {
            case 'peer-joined':
                this.addParticipant({
                    id: data.peerId,
                    displayName: data.displayName,
                    isHost: data.isHost,
                });
                this.showNotification(`${data.displayName} joined the call`);
                break;

            case 'peer-left':
                this.removeParticipant(data.peerId);
                break;

            case 'new-producer':
                await this.consumeProducer({
                    producerId: data.producerId,
                    peerId: data.peerId,
                    kind: data.kind,
                    displayName: data.displayName,
                });
                break;

            case 'consumer':
                await this.handleConsumer(data);
                break;

            case 'chat-message':
                this.handleChatMessage(data);
                break;

            case 'mute-audio':
                this.handlePeerMute(data.peerId, 'audio');
                break;

            case 'unmute-audio':
                this.handlePeerUnmute(data.peerId, 'audio');
                break;

            case 'host-action':
                this.handleHostAction(data.action, data.data);
                break;

            case 'room-locked':
                this.handleRoomLocked(true);
                break;

            case 'room-unlocked':
                this.handleRoomLocked(false);
                break;

            case 'mute-all-audio':
                this.handleMuteAll('audio', true);
                break;

            case 'unmute-all-audio':
                this.handleMuteAll('audio', false);
                break;

            case 'mute-all-video':
                this.handleMuteAll('video', true);
                break;

            case 'unmute-all-video':
                this.handleMuteAll('video', false);
                break;

            case 'participant-removed':
                if (data.targetPeerId === this.config.sessionId) {
                    this.handleRemovedByHost();
                } else {
                    this.removeParticipant(data.targetPeerId);
                }
                break;

            case 'screen-share-started':
                this.handlePeerScreenShare(data.peerId, true);
                break;

            case 'screen-share-stopped':
                this.handlePeerScreenShare(data.peerId, false);
                break;
        }
    },

    async createSendTransport(serverTransport) {
        this.state.sendTransport = this.config.device.createSendTransport(serverTransport);

        this.state.sendTransport.on('connect', async ({ dtlsParameters }, callback, errback) => {
            try {
                await this.sfuRequest(`/transport/${serverTransport.id}/connect`, 'POST', {
                    dtlsParameters,
                });
                callback();
            } catch (error) {
                errback(error);
            }
        });

        this.state.sendTransport.on('produce', async ({ kind, rtpParameters }, callback, errback) => {
            try {
                const result = await this.sfuRequest(`/transport/${serverTransport.id}/produce`, 'POST', {
                    peerId: this.config.sessionId,
                    kind,
                    rtpParameters,
                });
                callback({ id: result.producerId });
            } catch (error) {
                errback(error);
            }
        });

        this.state.sendTransport.on('connectionstatechange', (state) => {
            console.log('Send transport state:', state);
        });

        await this.produceMedia();
    },

    async produceMedia() {
        if (!this.state.sendTransport || !this.state.localStream) return;

        const audioTrack = this.state.localStream.getAudioTracks()[0];
        if (audioTrack) {
            try {
                const audioProducer = await this.state.sendTransport.produce({
                    track: audioTrack,
                    encodings: [{ maxBitrate: 128000 }],
                    codecOptions: { opusStereo: true, opusFec: true },
                });
                this.state.producers.set('audio', audioProducer);
                console.log('Audio producer created');
            } catch (error) {
                console.error('Error creating audio producer:', error);
            }
        }

        const videoTrack = this.state.localStream.getVideoTracks()[0];
        if (videoTrack) {
            try {
                const videoProducer = await this.state.sendTransport.produce({
                    track: videoTrack,
                    encodings: [
                        { id: 'low', maxBitrate: 150000, scaleResolutionDownBy: 4 },
                        { id: 'medium', maxBitrate: 500000, scaleResolutionDownBy: 2 },
                        { id: 'high', maxBitrate: 1500000 },
                    ],
                    codecOptions: { videoGoogleStartBitrate: 1000 },
                });
                this.state.producers.set('video', videoProducer);
                console.log('Video producer created');
            } catch (error) {
                console.error('Error creating video producer:', error);
            }
        }
    },

    async consumeProducer(producerInfo) {
        if (!this.state.sendTransport || !this.config.device) return;

        try {
            const canConsume = this.config.device.canConsume({
                producerId: producerInfo.producerId,
                rtpCapabilities: this.config.device.rtpCapabilities,
            });

            if (!canConsume) {
                console.warn('Cannot consume producer:', producerInfo.producerId);
                return;
            }

            const result = await this.sfuRequest(`/transport/${this.state.sendTransport.id}/consume`, 'POST', {
                peerId: this.config.sessionId,
                remotePeerId: producerInfo.peerId,
                producerId: producerInfo.producerId,
                rtpCapabilities: this.config.device.rtpCapabilities,
            });

            const consumer = await this.state.sendTransport.consume({
                id: result.consumerId,
                producerId: result.producerId,
                kind: result.kind,
                rtpParameters: result.rtpParameters,
            });

            this.state.consumers.set(consumer.id, {
                ...consumer,
                peerId: producerInfo.peerId,
                kind: producerInfo.kind,
                displayName: producerInfo.displayName,
            });

            this.handleRemoteStream(consumer, producerInfo);

        } catch (error) {
            console.error('Error consuming producer:', error);
        }
    },

    handleRemoteStream(consumer, peerInfo) {
        let videoContainer = document.querySelector(`[data-peer-id="${peerInfo.peerId}"]`);

        if (!videoContainer) {
            videoContainer = this.createVideoContainer(peerInfo.peerId, peerInfo.displayName);
            document.getElementById('videoGrid')?.appendChild(videoContainer);
        }

        const stream = new MediaStream();
        stream.addTrack(consumer.track);

        let video = videoContainer.querySelector('video');
        if (!video) {
            video = document.createElement('video');
            videoContainer.appendChild(video);
        }
        video.srcObject = stream;
        video.autoplay = true;
        video.playsinline = true;
        video.muted = true;
        video.style.webkitTransform = 'translateZ(0)';
        video.style.transform = 'translateZ(0)';

        const placeholder = videoContainer.querySelector('.video-placeholder');
        if (placeholder) {
            placeholder.style.display = 'none';
        }
        video.style.display = 'block';
        
        video.play({ playbackQuality: 'high' }).catch(() => {});

        this.updateParticipantsGrid();
    },

    createVideoContainer: function(peerId, displayName) {
        const container = document.createElement('div');
        container.className = 'video-container';
        container.dataset.peerId = peerId;

        const placeholder = document.createElement('div');
        placeholder.className = 'video-placeholder';
        placeholder.textContent = this.getInitials(displayName || 'P');

        const nameTag = document.createElement('div');
        nameTag.className = 'participant-name';
        nameTag.innerHTML = `<span>${displayName || 'Participant'}</span>`;

        container.appendChild(placeholder);
        container.appendChild(nameTag);

        return container;
    },

    removeVideoContainer: function(peerId) {
        const container = document.querySelector(`[data-peer-id="${peerId}"]`);
        if (container) {
            container.remove();
        }
        this.updateParticipantsGrid();
    },

    addParticipant: function(peer) {
        this.state.participants.set(peer.id, peer);
    },

    removeParticipant: function(peerId) {
        this.state.participants.delete(peerId);
        this.removeVideoContainer(peerId);
    },

    broadcastMessage: async function(message) {
        try {
            if (message.type === 'chat-message') {
                await this.sfuRequest(`/room/${this.config.roomCode}/chat`, 'POST', {
                    peerId: this.config.sessionId,
                    message: message.message,
                });
            } else if (message.type === 'host-action') {
                await this.sfuRequest(`/room/${this.config.roomCode}/host-action`, 'POST', {
                    peerId: this.config.sessionId,
                    action: message.action,
                    data: message,
                });
            } else {
                await this.sfuRequest(`/room/${this.config.roomCode}/broadcast`, 'POST', {
                    peerId: this.config.sessionId,
                    message,
                });
            }
        } catch (error) {
            console.error('Broadcast error:', error);
        }
    },

    toggleAudio: function() {
        if (!this.state.localStream) return;

        const audioTrack = this.state.localStream.getAudioTracks()[0];
        if (audioTrack) {
            audioTrack.enabled = !audioTrack.enabled;
            this.state.isAudioEnabled = audioTrack.enabled;

            const btn = document.getElementById('micBtn');
            if (btn) {
                if (this.state.isAudioEnabled) {
                    btn.classList.remove('active');
                    btn.innerHTML = '<i class="bi bi-mic-fill"></i>';
                    this.broadcastMessage({ type: 'unmute-audio' });
                } else {
                    btn.classList.add('active');
                    btn.innerHTML = '<i class="bi bi-mic-mute-fill"></i>';
                    this.broadcastMessage({ type: 'mute-audio' });
                }
            }

            this.updateParticipantStatus('is_audio_muted', !this.state.isAudioEnabled);
        }
    },

    toggleVideo: function() {
        if (!this.state.localStream) return;

        const videoTrack = this.state.localStream.getVideoTracks()[0];
        if (videoTrack) {
            videoTrack.enabled = !videoTrack.enabled;
            this.state.isVideoEnabled = videoTrack.enabled;

            const btn = document.getElementById('cameraBtn');
            const localVideo = document.getElementById('localVideo');
            const placeholder = document.getElementById('localVideoPlaceholder');

            if (btn) {
                if (this.state.isVideoEnabled) {
                    btn.classList.remove('active');
                    btn.innerHTML = '<i class="bi bi-camera-video-fill"></i>';
                } else {
                    btn.classList.add('active');
                    btn.innerHTML = '<i class="bi bi-camera-video-off-fill"></i>';
                }
            }

            if (localVideo) localVideo.style.display = this.state.isVideoEnabled ? 'block' : 'none';
            if (placeholder) placeholder.style.display = this.state.isVideoEnabled ? 'none' : 'flex';

            this.updateParticipantStatus('is_video_off', !this.state.isVideoEnabled);
        }
    },

    async toggleScreenShare: async function() {
        if (this.state.isScreenSharing) {
            await this.stopScreenShare();
        } else {
            await this.startScreenShare();
        }
    },

    async startScreenShare: async function() {
        try {
            await this.initScreenShare();
            this.state.isScreenSharing = true;

            const screenVideo = document.getElementById('screenShareVideo');
            if (screenVideo) {
                screenVideo.srcObject = this.state.screenStream;
                screenVideo.style.display = 'block';
            }

            const localVideo = document.getElementById('localVideo');
            if (localVideo) localVideo.style.display = 'none';

            const btn = document.getElementById('screenShareBtn');
            if (btn) {
                btn.classList.add('active', 'screen-share');
                btn.innerHTML = '<i class="bi bi-x-circle"></i>';
            }

            const indicator = document.getElementById('screenShareIndicator');
            if (indicator) indicator.classList.add('active');

            if (this.state.sendTransport) {
                const screenTrack = this.state.screenStream.getVideoTracks()[0];
                const videoProducer = this.state.producers.get('video');
                if (videoProducer) {
                    await videoProducer.replaceTrack({ track: screenTrack });
                }
            }

        } catch (error) {
            console.error('Error starting screen share:', error);
        }
    },

    async stopScreenShare: async function() {
        if (!this.state.isScreenSharing) return;

        if (this.state.screenStream) {
            this.state.screenStream.getTracks().forEach(track => track.stop());
            this.state.screenStream = null;
        }

        this.state.isScreenSharing = false;

        const screenVideo = document.getElementById('screenShareVideo');
        if (screenVideo) {
            screenVideo.style.display = 'none';
            screenVideo.srcObject = null;
        }

        const localVideo = document.getElementById('localVideo');
        if (localVideo && this.state.isVideoEnabled) {
            localVideo.style.display = 'block';
        }

        const btn = document.getElementById('screenShareBtn');
        if (btn) {
            btn.classList.remove('active', 'screen-share');
            btn.innerHTML = '<i class="bi bi-display"></i>';
        }

        const indicator = document.getElementById('screenShareIndicator');
        if (indicator) indicator.classList.remove('active');

        if (this.state.sendTransport && this.state.localStream) {
            const videoTrack = this.state.localStream.getVideoTracks()[0];
            const videoProducer = this.state.producers.get('video');
            if (videoProducer && videoTrack) {
                await videoProducer.replaceTrack({ track: videoTrack });
            }
        }
    },

    toggleRecording: function() {
        if (this.state.isRecording) {
            this.stopRecording();
        } else {
            this.startRecording();
        }
    },

    startRecording: function() {
        const combinedStream = new MediaStream();
        
        if (this.state.localStream) {
            this.state.localStream.getTracks().forEach(track => combinedStream.addTrack(track));
        }

        let mimeType = 'video/webm;codecs=vp9';
        if (!MediaRecorder.isTypeSupported(mimeType)) {
            mimeType = 'video/webm;codecs=vp8';
        }
        if (!MediaRecorder.isTypeSupported(mimeType)) {
            mimeType = 'video/webm';
        }

        try {
            this.state.mediaRecorder = new MediaRecorder(combinedStream, { mimeType });
        } catch (e) {
            console.error('Error creating MediaRecorder:', e);
            return;
        }

        this.state.recordedChunks = [];

        this.state.mediaRecorder.ondataavailable = (event) => {
            if (event.data.size > 0) {
                this.state.recordedChunks.push(event.data);
            }
        };

        this.state.mediaRecorder.onstop = () => {
            const blob = new Blob(this.state.recordedChunks, { type: 'video/webm' });
            this.downloadRecording(blob);
            this.uploadRecording(blob);
        };

        this.state.mediaRecorder.start(1000);
        this.state.isRecording = true;
        this.state.recordingStartTime = Date.now();

        const btn = document.getElementById('recordBtn');
        if (btn) {
            btn.classList.add('active', 'recording');
            btn.innerHTML = '<i class="bi bi-stop-circle-fill"></i>';
        }

        const indicator = document.getElementById('recordingIndicator');
        if (indicator) indicator.classList.add('active');
    },

    stopRecording: function() {
        if (this.state.mediaRecorder && this.state.mediaRecorder.state !== 'inactive') {
            this.state.mediaRecorder.stop();
        }

        this.state.isRecording = false;

        const btn = document.getElementById('recordBtn');
        if (btn) {
            btn.classList.remove('active', 'recording');
            btn.innerHTML = '<i class="bi bi-record-circle"></i>';
        }

        const indicator = document.getElementById('recordingIndicator');
        if (indicator) indicator.classList.remove('active');
    },

    downloadRecording: function(blob) {
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `recording_${this.config.roomCode}_${new Date().toISOString().replace(/[:.]/g, '-')}.webm`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
    },

    async uploadRecording: async function(blob) {
        const reader = new FileReader();
        reader.onloadend = async () => {
            const base64data = reader.result.split(',')[1];

            try {
                await fetch(this.config.apiBaseUrl + 'upload-recording/', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': this.getCsrfToken()
                    },
                    body: JSON.stringify({
                        room_code: this.config.roomCode,
                        session_id: this.config.sessionId,
                        recording_data: base64data,
                        duration_seconds: Math.floor((Date.now() - this.state.recordingStartTime) / 1000),
                        file_name: `recording_${this.config.roomCode}_${Date.now()}.webm`
                    })
                });
            } catch (error) {
                console.error('Error uploading recording:', error);
            }
        };
        reader.readAsDataURL(blob);
    },

    startCallTimer: function() {
        this.state.callStartTime = Date.now();

        this.state.callTimerInterval = setInterval(() => {
            const elapsed = Math.floor((Date.now() - this.state.callStartTime) / 1000);
            const hours = Math.floor(elapsed / 3600);
            const minutes = Math.floor((elapsed % 3600) / 60).toString().padStart(2, '0');
            const seconds = (elapsed % 60).toString().padStart(2, '0');

            const timerEl = document.getElementById('callTimer');
            if (timerEl) {
                timerEl.textContent = hours > 0 ? `${hours}:${minutes}:${seconds}` : `${minutes}:${seconds}`;
            }
        }, 1000);
    },

    updateConnectionStatus: function(status) {
        const statusEl = document.getElementById('connectionStatus');
        if (!statusEl) return;

        const dot = statusEl.querySelector('.connection-dot');
        const text = document.getElementById('connectionText');

        if (dot) {
            dot.className = 'connection-dot ' + status;
        }

        if (text) {
            switch (status) {
                case 'connected':
                case 'stable':
                    text.textContent = 'Connected';
                    if (dot) dot.style.background = '#28a745';
                    break;
                case 'connecting':
                    text.textContent = 'Connecting...';
                    if (dot) dot.style.background = '#ffc107';
                    break;
                case 'disconnected':
                case 'closed':
                    text.textContent = 'Disconnected';
                    if (dot) dot.style.background = '#dc3545';
                    break;
                case 'failed':
                    text.textContent = 'Connection Failed';
                    if (dot) dot.style.background = '#dc3545';
                    break;
                default:
                    text.textContent = status;
            }
        }
    },

    updateParticipantsList: function(participants) {
        const countEl = document.getElementById('participantCount');
        if (countEl) countEl.textContent = participants.length;

        const list = document.getElementById('participantsList');
        if (!list) return;

        list.innerHTML = '';

        participants.forEach(p => {
            if (p.id === this.config.sessionId) return;

            const item = document.createElement('div');
            item.className = 'participant-item';
            item.innerHTML = `
                <div class="avatar">${this.getInitials(p.displayName || 'P')}</div>
                <div class="info">
                    <div class="name">${this.escapeHtml(p.displayName || 'Participant')}</div>
                    <div class="status">
                        <i class="bi bi-mic"></i>
                        <i class="bi bi-camera-video"></i>
                    </div>
                </div>
                <div class="badges">
                    ${p.isHost ? '<span class="badge-icon host"><i class="bi bi-star"></i></span>' : ''}
                </div>
            `;
            list.appendChild(item);
        });
    },

    updateParticipantsGrid: function() {
        const grid = document.getElementById('videoGrid');
        if (!grid) return;

        const count = grid.children.length;
        if (count === 1) {
            grid.style.gridTemplateColumns = '1fr';
        } else if (count === 2) {
            grid.style.gridTemplateColumns = 'repeat(2, 1fr)';
        } else if (count <= 4) {
            grid.style.gridTemplateColumns = 'repeat(2, 1fr)';
        } else if (count <= 6) {
            grid.style.gridTemplateColumns = 'repeat(3, 1fr)';
        } else if (count <= 9) {
            grid.style.gridTemplateColumns = 'repeat(3, 1fr)';
        } else {
            grid.style.gridTemplateColumns = 'repeat(auto-fit, minmax(250px, 1fr))';
        }
    },

    getInitials: function(name) {
        return name.split(' ').map(n => n[0]).join('').substring(0, 2).toUpperCase();
    },

    handleChatMessage: function(data) {
        const messagesContainer = document.getElementById('chatMessages');
        if (!messagesContainer) return;

        const messageEl = document.createElement('div');
        messageEl.className = 'chat-message';
        messageEl.innerHTML = `
            <div class="sender">${this.escapeHtml(data.displayName || 'Guest')}</div>
            <div class="content">${this.escapeHtml(data.message)}</div>
        `;
        messagesContainer.appendChild(messageEl);
        messagesContainer.scrollTop = messagesContainer.scrollHeight;
    },

    sendChatMessage: function() {
        const input = document.getElementById('chatInput');
        if (!input) return;

        const message = input.value.trim();
        if (!message) return;

        this.broadcastMessage({
            type: 'chat-message',
            message: message,
            displayName: this.config.userName || 'Guest',
            timestamp: new Date().toISOString(),
        });

        input.value = '';
    },

    handleChatKeypress: function(event) {
        if (event.key === 'Enter') {
            this.sendChatMessage();
        }
    },

    handlePeerMute: function(peerId, type) {
        const container = document.querySelector(`[data-peer-id="${peerId}"]`);
        if (container) {
            container.classList.add('audio-muted');
        }
    },

    handlePeerUnmute: function(peerId, type) {
        const container = document.querySelector(`[data-peer-id="${peerId}"]`);
        if (container) {
            container.classList.remove('audio-muted');
        }
    },

    handleHostAction: function(action, data) {
        switch (action) {
            case 'lock_room':
                this.handleRoomLocked(true);
                this.showNotification('Room has been locked by the host');
                break;
            case 'unlock_room':
                this.handleRoomLocked(false);
                this.showNotification('Room has been unlocked');
                break;
            case 'mute_all_audio':
                this.handleMuteAll('audio', true);
                this.showNotification('Host muted all participants');
                break;
            case 'unmute_all_audio':
                this.handleMuteAll('audio', false);
                this.showNotification('Host unmuted all participants');
                break;
            case 'mute_all_video':
                this.handleMuteAll('video', true);
                this.showNotification('Host turned off all videos');
                break;
            case 'unmute_all_video':
                this.handleMuteAll('video', false);
                this.showNotification('Host turned on all videos');
                break;
            case 'remove_participant':
                if (data.targetSessionId === this.config.sessionId) {
                    this.handleRemovedByHost();
                }
                break;
            case 'mute_participant':
                if (data.targetSessionId === this.config.sessionId) {
                    this.toggleAudio(); 
                }
                break;
        }
    },

    handleRoomLocked: function(locked) {
        const indicator = document.getElementById('roomLockedIndicator');
        if (indicator) {
            indicator.classList.toggle('active', locked);
        }
        if (locked && !this.config.isHost) {
            const micBtn = document.getElementById('micBtn');
            const cameraBtn = document.getElementById('cameraBtn');
            if (micBtn) micBtn.disabled = true;
            if (cameraBtn) cameraBtn.disabled = true;
        }
    },

    handleMuteAll: function(type, muted) {
        if (type === 'audio' && muted) {
            if (this.state.isAudioEnabled) {
                this.toggleAudio();
            }
        } else if (type === 'audio' && !muted) {
            if (!this.state.isAudioEnabled) {
                this.toggleAudio();
            }
        } else if (type === 'video' && muted) {
            if (this.state.isVideoEnabled) {
                this.toggleVideo();
            }
        } else if (type === 'video' && !muted) {
            if (!this.state.isVideoEnabled) {
                this.toggleVideo();
            }
        }
    },

    handleRemovedByHost: function() {
        this.showNotification('You have been removed from the call by the host', 'error');
        setTimeout(() => {
            this.cleanup();
            window.location.href = '/videocalls/my-rooms/';
        }, 3000);
    },

    handlePeerScreenShare: function(peerId, sharing) {
        const container = document.querySelector(`[data-peer-id="${peerId}"]`);
        if (container) {
            container.classList.toggle('screen-sharing', sharing);
        }
    },

    showNotification: function(message, type = 'info') {
        const notification = document.createElement('div');
        notification.className = `sfu-notification sfu-notification-${type}`;
        notification.innerHTML = `
            <i class="bi bi-${type === 'error' ? 'exclamation-circle' : 'info-circle'}"></i>
            ${this.escapeHtml(message)}
        `;
        
        const style = document.createElement('style');
        style.textContent = `
            .sfu-notification {
                position: fixed;
                top: 20px;
                left: 50%;
                transform: translateX(-50%);
                background: rgba(0,0,0,0.9);
                color: white;
                padding: 12px 24px;
                border-radius: 8px;
                z-index: 999999;
                display: flex;
                align-items: center;
                gap: 10px;
                animation: slideDown 0.3s ease;
            }
            .sfu-notification-error {
                background: #dc3545;
            }
            @keyframes slideDown {
                from { top: -50px; opacity: 0; }
                to { top: 20px; opacity: 1; }
            }
        `;
        if (!document.querySelector('style[data-sfu-notifications]')) {
            style.setAttribute('data-sfu-notifications', 'true');
            document.head.appendChild(style);
        }
        
        document.body.appendChild(notification);
        setTimeout(() => {
            notification.style.animation = 'slideDown 0.3s ease reverse';
            setTimeout(() => notification.remove(), 300);
        }, 3000);
    },

    toggleSidebar: function(type) {
        if (type === 'participants') {
            const sidebar = document.getElementById('participantsSidebar');
            const chat = document.getElementById('chatPanel');
            if (sidebar) sidebar.classList.toggle('show');
            if (chat) chat.classList.remove('show');
        } else if (type === 'chat') {
            const sidebar = document.getElementById('participantsSidebar');
            const chat = document.getElementById('chatPanel');
            if (chat) chat.classList.toggle('show');
            if (sidebar) sidebar.classList.remove('show');
        }
    },

    copyRoomLink: function() {
        const roomLink = `${window.location.origin}/videocalls/room/${this.config.roomCode}/`;
        navigator.clipboard.writeText(roomLink).then(() => {
            alert('Room link copied to clipboard!');
        }).catch(() => {
            prompt('Copy this room link:', roomLink);
        });
    },

    async updateParticipantStatus: async function(field, value) {
        try {
            await fetch(this.config.apiBaseUrl + 'update-participant/', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this.getCsrfToken()
                },
                body: JSON.stringify({
                    room_code: this.config.roomCode,
                    session_id: this.config.sessionId,
                    [field]: value
                })
            });
        } catch (error) {
            console.error('Error updating participant status:', error);
        }
    },

    async endCall: async function() {
        if (!confirm('Are you sure you want to end this call?')) return;

        if (this.state.isRecording) {
            this.stopRecording();
        }

        this.cleanup();

        try {
            await this.sfuRequest(`/peer/${this.config.sessionId}/leave`, 'POST');
        } catch (error) {
            console.error('Error leaving SFU room:', error);
        }

        if (this.config.isHost) {
            try {
                await fetch(`/videocalls/end/${this.config.roomCode}/`, {
                    method: 'POST',
                    headers: {
                        'X-CSRFToken': this.getCsrfToken()
                    }
                });
            } catch (error) {
                console.error('Error ending room:', error);
            }
        } else {
            try {
                await fetch(this.config.apiBaseUrl + 'leave/', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': this.getCsrfToken()
                    },
                    body: JSON.stringify({
                        room_code: this.config.roomCode,
                        session_id: this.config.sessionId
                    })
                });
            } catch (error) {
                console.error('Error leaving room:', error);
            }
        }

        window.location.href = '/videocalls/my-rooms/';
    },

    escapeHtml: function(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    },

    cleanup: function() {
        this.stopPolling();

        if (this.state.callTimerInterval) {
            clearInterval(this.state.callTimerInterval);
        }

        this.state.producers.forEach(producer => producer.close());
        this.state.producers.clear();

        this.state.consumers.forEach(consumer => consumer.close());
        this.state.consumers.clear();

        if (this.state.sendTransport) {
            this.state.sendTransport.close();
        }

        if (this.state.localStream) {
            this.state.localStream.getTracks().forEach(track => track.stop());
        }

        if (this.state.screenStream) {
            this.state.screenStream.getTracks().forEach(track => track.stop());
        }

        if (this.state.isRecording) {
            this.stopRecording();
        }
    }
};

if (typeof window !== 'undefined') {
    window.SFUVideoCall = SFUVideoCall;
}
