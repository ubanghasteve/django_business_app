const VideoCallManager = {
    config: {
        roomCode: null,
        roomName: null,
        isHost: false,
        userName: '',
        userEmail: '',
        userId: null,
        sessionId: null,
        apiBaseUrl: '/videocalls/api/',
        pollInterval: 300,
        iceServers: [
            { urls: 'stun:stun.l.google.com:19302' },
            { urls: 'stun:stun1.l.google.com:19302' },
            { urls: 'stun:stun2.l.google.com:19302' }
        ]
    },
    
    state: {
        localStream: null,
        screenStream: null,
        peerConnections: {},
        mediaRecorder: null,
        recordedChunks: [],
        isRecording: false,
        isScreenSharing: false,
        isAudioEnabled: true,
        isVideoEnabled: true,
        callStartTime: null,
        recordingStartTime: null,
        callTimerInterval: null,
        recordingTimerInterval: null,
        signalingPollInterval: null,
        chatMessages: []
    },
    
    init: async function(config) {
        Object.assign(this.config, config);
        this.config.sessionId = this.generateSessionId();
        this.bindEvents();
        
        await this.loadConfig();
    },
    
    loadConfig: async function() {
        try {
            const response = await fetch('/videocalls/api/config/');
            const data = await response.json();
            
            if (data.success) {
                if (data.config.iceServers && data.config.iceServers.length > 0) {
                    this.config.iceServers = data.config.iceServers;
                }
                if (data.config.pollInterval) {
                    this.config.pollInterval = data.config.pollInterval;
                }
                console.log('Video call config loaded:', {
                    iceServersCount: this.config.iceServers.length,
                    pollInterval: this.config.pollInterval
                });
            }
        } catch (error) {
            console.warn('Failed to load video call config, using defaults:', error);
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
            if (document.visibilityState === 'visible') {
                this.startSignalingPoll();
            } else {
                this.stopSignalingPoll();
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
            
            return this.state.localStream;
        } catch (error) {
            console.error('Error accessing media devices:', error);
            throw error;
        }
    },
    
    async initScreenShare() {
        try {
            this.state.screenStream = await navigator.mediaDevices.getDisplayMedia({
                video: {
                    cursor: 'always',
                    displaySurface: 'monitor'
                },
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
            }
            
            return data;
        } catch (error) {
            console.error('Error joining room:', error);
            this.updateConnectionStatus('disconnected');
            throw error;
        }
    },
    
    createPeerConnection: function(targetSessionId) {
        if (this.state.peerConnections[targetSessionId]) {
            return this.state.peerConnections[targetSessionId];
        }
        
        const pc = new RTCPeerConnection({ 
            iceServers: this.config.iceServers,
            iceCandidatePoolSize: 10,
            bundlePolicy: 'max-bundle',
            rtcpMuxPolicy: 'require',
            iceTransportPolicy: 'all',
            iceServersTimeout: 5000
        });
        
        if (this.state.localStream) {
            this.state.localStream.getTracks().forEach(track => {
                pc.addTrack(track, this.state.localStream);
            });
        }
        
        if (this.state.screenStream) {
            this.state.screenStream.getTracks().forEach(track => {
                pc.addTrack(track, this.state.screenStream);
            });
        }
        
        setTimeout(() => {
            pc.getSenders().forEach(sender => {
                if (sender.track) {
                    const params = sender.getParameters();
                    if (sender.track.kind === 'video') {
                        if (!params.encodings) params.encodings = [{}];
                        params.encodings[0].maxBitrate = 2500000;
                        params.encodings[0].minBitrate = 300000;
                        params.encodings[0].priority = 'high';
                        params.encodings[0].networkPriority = 'high';
                        params.encodings[0].active = true;
                        
                        if (params.codecs) {
                            params.codecs.forEach(codec => {
                                if (codec.mimeType === 'video/VP8' || codec.mimeType === 'video/VP9') {
                                    codec.signalingFeedback = true;
                                }
                            });
                        }
                        
                        sender.setParameters(params).catch(() => {});
                        
                        sender.track.applyConstraints({
                            width: { ideal: 1280 },
                            height: { ideal: 720 },
                            frameRate: { ideal: 30 }
                        }).catch(() => {});
                    }
                    if (sender.track.kind === 'audio') {
                        if (!params.encodings) params.encodings = [{}];
                        params.encodings[0].maxBitrate = 128000;
                        params.encodings[0].priority = 'high';
                        sender.setParameters(params).catch(() => {});
                    }
                }
            });
        }, 0);
        
        pc.ontrack = (event) => {
            this.handleRemoteStream(event.streams[0], targetSessionId);
        };
        
        pc.onicecandidate = (event) => {
            if (event.candidate) {
                this.sendIceCandidate(targetSessionId, event.candidate);
            }
        };
        
        pc.onconnectionstatechange = () => {
            this.updateConnectionStatus(pc.connectionState);
        };
        
        pc.oniceconnectionstatechange = () => {
            if (pc.iceConnectionState === 'failed') {
                this.reconnectPeer(targetSessionId);
            }
        };
        
        this.state.peerConnections[targetSessionId] = pc;
        return pc;
    },
    
    async createOffer: async function(targetSessionId) {
        const pc = this.createPeerConnection(targetSessionId);
        
        try {
            const offer = await pc.createOffer();
            await pc.setLocalDescription(offer);
            
            await this.sendSignalingMessage({
                type: 'offer',
                target_session_id: targetSessionId,
                payload: { sdp: offer.sdp, type: offer.type }
            });
            
            return offer;
        } catch (error) {
            console.error('Error creating offer:', error);
            throw error;
        }
    },
    
    async createAnswer: async function(offer, targetSessionId) {
        const pc = this.createPeerConnection(targetSessionId);
        
        try {
            await pc.setRemoteDescription(new RTCSessionDescription(offer));
            
            const answer = await pc.createAnswer();
            await pc.setLocalDescription(answer);
            
            await this.sendSignalingMessage({
                type: 'answer',
                target_session_id: targetSessionId,
                payload: { sdp: answer.sdp, type: answer.type }
            });
            
            return answer;
        } catch (error) {
            console.error('Error creating answer:', error);
            throw error;
        }
    },
    
    async sendIceCandidate: async function(targetSessionId, candidate) {
        try {
            await this.sendSignalingMessage({
                type: 'ice_candidate',
                target_session_id: targetSessionId,
                payload: { candidate: candidate }
            });
        } catch (error) {
            console.error('Error sending ICE candidate:', error);
        }
    },
    
    async sendSignalingMessage: async function(data) {
        try {
            await fetch(this.config.apiBaseUrl + 'signaling/', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this.getCsrfToken()
                },
                body: JSON.stringify({
                    room_code: this.config.roomCode,
                    sender_session_id: this.config.sessionId,
                    message_type: data.type,
                    target_session_id: data.target_session_id || '',
                    payload: data.payload
                })
            });
        } catch (error) {
            console.error('Error sending signaling message:', error);
        }
    },
    
    startSignalingPoll: function() {
        if (this.state.signalingPollInterval) return;
        
        this.state.signalingPollInterval = setInterval(async () => {
            await this.pollSignalingMessages();
            await this.pollParticipants();
        }, this.config.pollInterval);
    },
    
    stopSignalingPoll: function() {
        if (this.state.signalingPollInterval) {
            clearInterval(this.state.signalingPollInterval);
            this.state.signalingPollInterval = null;
        }
    },
    
    async pollSignalingMessages: async function() {
        try {
            const response = await fetch(
                `${this.config.apiBaseUrl}signaling/messages/?room_code=${this.config.roomCode}&session_id=${this.config.sessionId}`
            );
            const data = await response.json();
            
            if (data.messages && data.messages.length > 0) {
                for (const msg of data.messages) {
                    await this.handleSignalingMessage(msg);
                }
            }
        } catch (error) {
            console.error('Error polling signaling messages:', error);
        }
    },
    
    async pollParticipants: async function() {
        try {
            const response = await fetch(`${this.config.apiBaseUrl}participants/${this.config.roomCode}/`);
            const data = await response.json();
            
            if (data.success) {
                this.updateParticipantsList(data.participants);
                
                for (const participant of data.participants) {
                    if (participant.session_id !== this.config.sessionId) {
                        if (!this.state.peerConnections[participant.session_id]) {
                            await this.createOffer(participant.session_id);
                        }
                    }
                }
            }
        } catch (error) {
            console.error('Error polling participants:', error);
        }
    },
    
    async handleSignalingMessage: async function(msg) {
        if (msg.sender_session_id === this.config.sessionId) return;
        
        switch (msg.message_type) {
            case 'offer':
                await this.createAnswer(msg.payload.sdp, msg.sender_session_id);
                break;
            case 'answer':
                const pc = this.state.peerConnections[msg.sender_session_id];
                if (pc && msg.payload.sdp) {
                    await pc.setRemoteDescription(new RTCSessionDescription(msg.payload.sdp));
                }
                break;
            case 'ice_candidate':
                const icePc = this.state.peerConnections[msg.sender_session_id];
                if (icePc && msg.payload.candidate) {
                    try {
                        await icePc.addIceCandidate(new RTCIceCandidate(msg.payload.candidate));
                    } catch (e) {
                        console.error('Error adding ICE candidate:', e);
                    }
                }
                break;
            case 'screen_share_start':
                this.handleScreenShareStart(msg.sender_session_id);
                break;
            case 'screen_share_stop':
                this.handleScreenShareStop(msg.sender_session_id);
                break;
            case 'chat':
                this.handleIncomingChatMessage(msg.payload);
                break;
        }
    },
    
    handleRemoteStream: function(stream, sessionId) {
        let videoContainer = document.querySelector(`[data-session-id="${sessionId}"]`);
        
        if (!videoContainer) {
            videoContainer = this.createVideoContainer(sessionId);
            document.getElementById('videoGrid')?.appendChild(videoContainer);
        }
        
        const video = videoContainer.querySelector('video') || document.createElement('video');
        video.srcObject = stream;
        video.autoplay = true;
        video.playsinline = true;
        video.muted = true;
        video.style.webkitTransform = 'translateZ(0)';
        video.style.transform = 'translateZ(0)';
        
        if (!videoContainer.contains(video)) {
            videoContainer.appendChild(video);
        }
        
        const placeholder = videoContainer.querySelector('.video-placeholder');
        if (placeholder) {
            placeholder.style.display = 'none';
        }
        video.style.display = 'block';
        
        video.play({ playbackQuality: 'high' }).catch(() => {});
        
        this.updateParticipantsGrid();
    },
    
    createVideoContainer: function(sessionId) {
        const container = document.createElement('div');
        container.className = 'video-container';
        container.dataset.sessionId = sessionId;
        
        const placeholder = document.createElement('div');
        placeholder.className = 'video-placeholder';
        placeholder.textContent = 'P';
        
        const nameTag = document.createElement('div');
        nameTag.className = 'participant-name';
        nameTag.innerHTML = `<span>Participant</span>`;
        
        container.appendChild(placeholder);
        container.appendChild(nameTag);
        
        return container;
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
                } else {
                    btn.classList.add('active');
                    btn.innerHTML = '<i class="bi bi-mic-mute-fill"></i>';
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
            
            const screenTrack = this.state.screenStream.getVideoTracks()[0];
            for (const pc of Object.values(this.state.peerConnections)) {
                const sender = pc.getSenders().find(s => s.track?.kind === 'video');
                if (sender) {
                    await sender.replaceTrack(screenTrack);
                }
            }
            
            this.broadcastScreenShare(true);
            this.updateParticipantStatus('is_screen_sharing', true);
            
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
        
        if (this.state.localStream) {
            const videoTrack = this.state.localStream.getVideoTracks()[0];
            for (const pc of Object.values(this.state.peerConnections)) {
                const sender = pc.getSenders().find(s => s.track?.kind === 'video');
                if (sender && videoTrack) {
                    await sender.replaceTrack(videoTrack);
                }
            }
        }
        
        this.broadcastScreenShare(false);
        this.updateParticipantStatus('is_screen_sharing', false);
    },
    
    broadcastScreenShare: function(isSharing) {
        this.sendSignalingMessage({
            type: isSharing ? 'screen_share_start' : 'screen_share_stop',
            payload: {}
        });
    },
    
    handleScreenShareStart: function(sessionId) {
        const container = document.querySelector(`[data-session-id="${sessionId}"]`);
        if (container) container.classList.add('screen-sharing');
    },
    
    handleScreenShareStop: function(sessionId) {
        const container = document.querySelector(`[data-session-id="${sessionId}"]`);
        if (container) container.classList.remove('screen-sharing');
    },
    
    toggleRecording: function() {
        if (this.state.isRecording) {
            this.stopRecording();
        } else {
            this.startRecording();
        }
    },
    
    startRecording: function() {
        const streamToRecord = this.state.screenStream || this.state.localStream;
        if (!streamToRecord) return;
        
        let mimeType = 'video/webm;codecs=vp9';
        if (!MediaRecorder.isTypeSupported(mimeType)) {
            mimeType = 'video/webm;codecs=vp8';
        }
        if (!MediaRecorder.isTypeSupported(mimeType)) {
            mimeType = 'video/webm';
        }
        
        try {
            this.state.mediaRecorder = new MediaRecorder(streamToRecord, { mimeType });
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
        
        this.state.recordingTimerInterval = setInterval(() => {
            const elapsed = Math.floor((Date.now() - this.state.recordingStartTime) / 1000);
            const minutes = Math.floor(elapsed / 60).toString().padStart(2, '0');
            const seconds = (elapsed % 60).toString().padStart(2, '0');
            const recordingTimeEl = document.getElementById('recordingTime');
            if (recordingTimeEl) recordingTimeEl.textContent = `${minutes}:${seconds}`;
        }, 1000);
    },
    
    stopRecording: function() {
        if (this.state.mediaRecorder && this.state.mediaRecorder.state !== 'inactive') {
            this.state.mediaRecorder.stop();
        }
        
        this.state.isRecording = false;
        
        if (this.state.recordingTimerInterval) {
            clearInterval(this.state.recordingTimerInterval);
            this.state.recordingTimerInterval = null;
        }
        
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
                    text.textContent = 'Connected';
                    break;
                case 'connecting':
                    text.textContent = 'Connecting...';
                    break;
                case 'disconnected':
                    text.textContent = 'Disconnected';
                    break;
                case 'failed':
                    text.textContent = 'Connection Failed';
                    break;
                default:
                    text.textContent = 'Unknown';
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
            if (p.session_id === this.config.sessionId) return;
            
            const item = document.createElement('div');
            item.className = 'participant-item';
            item.innerHTML = `
                <div class="avatar">${this.getInitials(p.display_name || p.participant_name || 'P')}</div>
                <div class="info">
                    <div class="name">${p.display_name || p.participant_name || 'Participant'}</div>
                    <div class="status">
                        ${p.is_audio_muted ? '<i class="bi bi-mic-mute"></i>' : '<i class="bi bi-mic"></i>'}
                        ${p.is_video_off ? '<i class="bi bi-camera-video-off"></i>' : '<i class="bi bi-camera-video"></i>'}
                    </div>
                </div>
                <div class="badges">
                    ${p.is_host ? '<span class="badge-icon host"><i class="bi bi-star"></i></span>' : ''}
                    ${p.is_screen_sharing ? '<span class="badge-icon screen"><i class="bi bi-display"></i></span>' : ''}
                    ${p.is_audio_muted ? '<span class="badge-icon muted"><i class="bi bi-mic-mute"></i></span>' : ''}
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
        } else {
            grid.style.gridTemplateColumns = 'repeat(auto-fit, minmax(300px, 1fr))';
        }
    },
    
    getInitials: function(name) {
        return name.split(' ').map(n => n[0]).join('').substring(0, 2).toUpperCase();
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
    
    sendChatMessage: function() {
        const input = document.getElementById('chatInput');
        if (!input) return;
        
        const message = input.value.trim();
        if (!message) return;
        
        this.sendSignalingMessage({
            type: 'chat',
            payload: {
                message: message,
                sender_name: this.config.userName || 'Guest',
                timestamp: new Date().toISOString()
            }
        });
        
        input.value = '';
    },
    
    handleChatKeypress: function(event) {
        if (event.key === 'Enter') {
            this.sendChatMessage();
        }
    },
    
    handleIncomingChatMessage: function(payload) {
        const messagesContainer = document.getElementById('chatMessages');
        if (!messagesContainer) return;
        
        const messageEl = document.createElement('div');
        messageEl.className = 'chat-message';
        messageEl.innerHTML = `
            <div class="sender">${this.escapeHtml(payload.sender_name)}</div>
            <div class="content">${this.escapeHtml(payload.message)}</div>
        `;
        messagesContainer.appendChild(messageEl);
        messagesContainer.scrollTop = messagesContainer.scrollHeight;
    },
    
    escapeHtml: function(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
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
    
    copyRoomLink: function() {
        const roomLink = `${window.location.origin}/videocalls/room/${this.config.roomCode}/`;
        navigator.clipboard.writeText(roomLink).then(() => {
            alert('Room link copied to clipboard!');
        }).catch(() => {
            prompt('Copy this room link:', roomLink);
        });
    },
    
    async endCall: async function() {
        if (!confirm('Are you sure you want to end this call?')) return;
        
        if (this.state.isRecording) {
            this.stopRecording();
        }
        
        this.cleanup();
        
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
    
    reconnectPeer: async function(sessionId) {
        if (this.state.peerConnections[sessionId]) {
            this.state.peerConnections[sessionId].close();
            delete this.state.peerConnections[sessionId];
        }
        
        await this.createOffer(sessionId);
    },
    
    handlePeerDisconnect: function(sessionId) {
        if (this.state.peerConnections[sessionId]) {
            this.state.peerConnections[sessionId].close();
            delete this.state.peerConnections[sessionId];
        }
        
        const container = document.querySelector(`[data-session-id="${sessionId}"]`);
        if (container) {
            container.remove();
        }
        
        this.updateParticipantsGrid();
    },
    
    cleanup: function() {
        this.stopSignalingPoll();
        
        if (this.state.callTimerInterval) {
            clearInterval(this.state.callTimerInterval);
        }
        
        if (this.state.recordingTimerInterval) {
            clearInterval(this.state.recordingTimerInterval);
        }
        
        Object.values(this.state.peerConnections).forEach(pc => pc.close());
        this.state.peerConnections = {};
        
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
    window.VideoCallManager = VideoCallManager;
}
