/**
 * Virtual Background Module for Video Calls
 * Uses TensorFlow.js and BodyPix for real-time background segmentation
 */

class VirtualBackground {
    constructor() {
        this.bodyPix = null;
        this.isLoaded = false;
        this.isEnabled = false;
        this.currentBackground = null;
        this.backgroundType = 'blur'; // 'blur', 'image', 'color'
        this.blurAmount = 10;
        this.color = '#1a1a2e';
        this.canvas = null;
        this.ctx = null;
        this.processing = false;
        this.animationFrame = null;
        
        // Available backgrounds
        this.backgrounds = {
            blur: { name: 'Blur', icon: 'bi-droplet' },
            none: { name: 'None', icon: 'bi-x-circle' },
            office: { name: 'Office', icon: 'bi-building' },
            nature: { name: 'Nature', icon: 'bi-tree' },
            city: { name: 'City', icon: 'bi-building' },
            abstract: { name: 'Abstract', icon: 'bi-palette' }
        };
        
        // Preloaded background images
        this.backgroundImages = {};
    }

    /**
     * Initialize TensorFlow.js and BodyPix
     */
    async init() {
        try {
            console.log('Loading TensorFlow.js for virtual background...');
            
            // Import TensorFlow.js
            await this.loadScript('https://cdn.jsdelivr.net/npm/@tensorflow/tfjs@4.10.0/dist/tf.min.js');
            
            // Import BodyPix for segmentation
            await this.loadScript('https://cdn.jsdelivr.net/npm/@tensorflow-models/body-pix@2.2.0/dist/body-pix.min.js');
            
            // Load BodyPix model
            this.bodyPix = await bodyPix.load({
                architecture: 'MobileNetV1',
                outputStride: 16,
                multiplier: 0.75,
                quantBytes: 2
            });
            
            this.isLoaded = true;
            console.log('Virtual Background loaded successfully');
            
            // Preload background images
            await this.preloadBackgrounds();
            
            return true;
        } catch (error) {
            console.error('Failed to load virtual background:', error);
            return false;
        }
    }

    /**
     * Load external script
     */
    loadScript(src) {
        return new Promise((resolve, reject) => {
            const script = document.createElement('script');
            script.src = src;
            script.onload = resolve;
            script.onerror = reject;
            document.head.appendChild(script);
        });
    }

    /**
     * Preload background images
     */
    async preloadBackgrounds() {
        const backgrounds = {
            office: '/static/videocalls/backgrounds/office.jpg',
            nature: '/static/videocalls/backgrounds/nature.jpg',
            city: '/static/videocalls/backgrounds/city.jpg',
            abstract: '/static/videocalls/backgrounds/abstract.jpg'
        };

        for (const [name, src] of Object.entries(backgrounds)) {
            try {
                const img = new Image();
                img.crossOrigin = 'anonymous';
                await new Promise((resolve, reject) => {
                    img.onload = resolve;
                    img.onerror = reject;
                    img.src = src;
                });
                this.backgroundImages[name] = img;
            } catch (error) {
                console.warn(`Failed to load background: ${name}`);
            }
        }
    }

    /**
     * Create virtual background canvas
     */
    createCanvas(videoElement) {
        this.canvas = document.createElement('canvas');
        this.canvas.width = videoElement.videoWidth || 1280;
        this.canvas.height = videoElement.videoHeight || 720;
        this.ctx = this.canvas.getContext('2d');
        return this.canvas;
    }

    /**
     * Process video frame with virtual background
     */
    async processFrame(videoElement) {
        if (!this.isLoaded || !this.bodyPix || !this.ctx || this.processing) {
            return;
        }

        this.processing = true;

        try {
            // Run BodyPix segmentation
            const segmentation = await this.bodyPix.segmentPerson(videoElement, {
                multiSegmentation: false,
                segmentBodyParts: false
            });

            // Clear canvas
            this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);

            // Draw background
            if (this.currentBackground === 'blur') {
                await this.drawBlurredBackground(videoElement, segmentation);
            } else if (this.currentBackground === 'none') {
                this.ctx.drawImage(videoElement, 0, 0, this.canvas.width, this.canvas.height);
            } else if (this.backgroundImages[this.currentBackground]) {
                this.drawImageBackground(this.backgroundImages[this.currentBackground]);
            } else {
                this.drawColorBackground(this.color);
            }

            // Draw person with background removed
            this.drawPersonWithoutBackground(videoElement, segmentation);

        } catch (error) {
            console.error('Error processing frame:', error);
            // Fallback: just draw video
            this.ctx.drawImage(videoElement, 0, 0, this.canvas.width, this.canvas.height);
        }

        this.processing = false;
    }

    /**
     * Draw blurred background
     */
    async drawBlurredBackground(videoElement, segmentation) {
        // Draw the original video
        this.ctx.drawImage(videoElement, 0, 0, this.canvas.width, this.canvas.height);
        
        // Get image data
        const imageData = this.ctx.getImageData(0, 0, this.canvas.width, this.canvas.height);
        const data = imageData.data;
        
        // Apply simple blur to background (outside person mask)
        const width = this.canvas.width;
        const height = this.canvas.height;
        
        // Create output buffer
        const output = new Uint8ClampedArray(data.length);
        
        // Simple box blur for background
        for (let y = 0; y < height; y++) {
            for (let x = 0; x < width; x++) {
                const idx = (y * width + x) * 4;
                const maskIdx = y * width + x;
                
                // If this pixel is background (not person), blur it
                if (!segmentation.data[maskIdx]) {
                    let r = 0, g = 0, b = 0, count = 0;
                    
                    // Simple 3x3 blur
                    for (let dy = -2; dy <= 2; dy++) {
                        for (let dx = -2; dx <= 2; dx++) {
                            const nx = Math.min(Math.max(x + dx, 0), width - 1);
                            const ny = Math.min(Math.max(y + dy, 0), height - 1);
                            const nidx = (ny * width + nx) * 4;
                            r += data[nidx];
                            g += data[nidx + 1];
                            b += data[nidx + 2];
                            count++;
                        }
                    }
                    
                    output[idx] = r / count;
                    output[idx + 1] = g / count;
                    output[idx + 2] = b / count;
                    output[idx + 3] = 255;
                } else {
                    output[idx] = data[idx];
                    output[idx + 1] = data[idx + 1];
                    output[idx + 2] = data[idx + 2];
                    output[idx + 3] = data[idx + 3];
                }
            }
        }
        
        // Draw blurred background
        const blurredData = new ImageData(output, width, height);
        this.ctx.putImageData(blurredData, 0, 0);
    }

    /**
     * Draw image background
     */
    drawImageBackground(img) {
        // Cover fit the image
        const imgRatio = img.width / img.height;
        const canvasRatio = this.canvas.width / this.canvas.height;
        
        let sx = 0, sy = 0, sw = img.width, sh = img.height;
        
        if (imgRatio > canvasRatio) {
            // Image is wider
            sw = img.height * canvasRatio;
            sx = (img.width - sw) / 2;
        } else {
            // Image is taller
            sh = img.width / canvasRatio;
            sy = (img.height - sh) / 2;
        }
        
        this.ctx.drawImage(img, sx, sy, sw, sh, 0, 0, this.canvas.width, this.canvas.height);
    }

    /**
     * Draw solid color background
     */
    drawColorBackground(color) {
        this.ctx.fillStyle = color;
        this.ctx.fillRect(0, 0, this.canvas.width, this.canvas.height);
    }

    /**
     * Draw person without background
     */
    drawPersonWithoutBackground(videoElement, segmentation) {
        const tempCanvas = document.createElement('canvas');
        tempCanvas.width = this.canvas.width;
        tempCanvas.height = this.canvas.height;
        const tempCtx = tempCanvas.getContext('2d');
        
        // Draw original video
        tempCtx.drawImage(videoElement, 0, 0, this.canvas.width, this.canvas.height);
        
        // Get image data
        const imageData = tempCtx.getImageData(0, 0, this.canvas.width, this.canvas.height);
        const data = imageData.data;
        
        // Remove background (set alpha to 0 for background pixels)
        for (let i = 0; i < segmentation.data.length; i++) {
            if (!segmentation.data[i]) {
                data[i * 4 + 3] = 0; // Set alpha to 0
            }
        }
        
        // Draw person on top
        tempCtx.putImageData(imageData, 0, 0);
        this.ctx.drawImage(tempCanvas, 0, 0);
    }

    /**
     * Set background
     */
    setBackground(type, value = null) {
        this.currentBackground = type;
        
        if (type === 'blur') {
            this.backgroundType = 'blur';
        } else if (type === 'color') {
            this.backgroundType = 'color';
            this.color = value || '#1a1a2e';
        } else if (type === 'image') {
            this.backgroundType = 'image';
            this.currentBackground = value;
        } else if (type === 'none') {
            this.backgroundType = 'none';
        }
    }

    /**
     * Start processing frames
     */
    startProcessing(videoElement, onFrame) {
        if (!this.isLoaded) return;

        const process = async () => {
            if (this.isEnabled && videoElement.readyState >= 2) {
                await this.processFrame(videoElement);
                
                if (onFrame && this.canvas) {
                    onFrame(this.canvas);
                }
            }
            this.animationFrame = requestAnimationFrame(process);
        };

        process();
    }

    /**
     * Stop processing
     */
    stopProcessing() {
        if (this.animationFrame) {
            cancelAnimationFrame(this.animationFrame);
            this.animationFrame = null;
        }
    }

    /**
     * Enable/disable
     */
    enable() {
        this.isEnabled = true;
    }

    disable() {
        this.isEnabled = false;
    }

    toggle() {
        this.isEnabled = !this.isEnabled;
        return this.isEnabled;
    }

    /**
     * Cleanup
     */
    cleanup() {
        this.stopProcessing();
        if (this.canvas) {
            this.canvas = null;
            this.ctx = null;
        }
    }
}

/**
 * Alternative: Simple CSS-based background blur (no AI)
 * Uses just-in-time background segmentation approximation
 */
class SimpleVirtualBackground {
    constructor() {
        this.canvas = null;
        this.ctx = null;
        this.isEnabled = false;
        this.blurAmount = 15;
        this.color = '#1a1a2e';
    }

    async init() {
        console.log('Simple Virtual Background initialized (CSS-based)');
        return true;
    }

    createCanvas(videoElement) {
        this.canvas = document.createElement('canvas');
        this.canvas.width = videoElement.videoWidth || 1280;
        this.canvas.height = videoElement.videoHeight || 720;
        this.ctx = this.canvas.getContext('2d');
        return this.canvas;
    }

    setBackground(type, value = null) {
        if (type === 'blur') {
            this.blurAmount = value || 15;
        } else if (type === 'color') {
            this.color = value || '#1a1a2e';
        }
    }

    async processFrame(videoElement) {
        if (!this.ctx) return;

        // Simply draw video or solid color
        if (this.currentBackground === 'none' || !this.currentBackground) {
            this.ctx.drawImage(videoElement, 0, 0, this.canvas.width, this.canvas.height);
        } else {
            // Draw background
            this.ctx.fillStyle = this.color;
            this.ctx.fillRect(0, 0, this.canvas.width, this.canvas.height);
            
            // Draw video with rounded corners
            this.ctx.save();
            this.roundRect(0, 0, this.canvas.width, this.canvas.height, 20);
            this.ctx.clip();
            this.ctx.drawImage(videoElement, 0, 0, this.canvas.width, this.canvas.height);
            this.ctx.restore();
        }
    }

    roundRect(x, y, width, height, radius) {
        this.ctx.beginPath();
        this.ctx.moveTo(x + radius, y);
        this.ctx.lineTo(x + width - radius, y);
        this.ctx.quadraticCurveTo(x + width, y, x + width, y + radius);
        this.ctx.lineTo(x + width, y + height - radius);
        this.ctx.quadraticCurveTo(x + width, y + height, x + width - radius, y + height);
        this.ctx.lineTo(x + radius, y + height);
        this.ctx.quadraticCurveTo(x, y + height, x, y + height - radius);
        this.ctx.lineTo(x, y + radius);
        this.ctx.quadraticCurveTo(x, y, x + radius, y);
        this.ctx.closePath();
    }

    enable() { this.isEnabled = true; }
    disable() { this.isEnabled = false; }
    toggle() { this.isEnabled = !this.isEnabled; return this.isEnabled; }

    startProcessing(videoElement, onFrame) {
        const process = async () => {
            if (this.isEnabled) {
                await this.processFrame(videoElement);
                if (onFrame && this.canvas) onFrame(this.canvas);
            }
            requestAnimationFrame(process);
        };
        process();
    }

    stopProcessing() {}
    cleanup() {}
}

// Export
window.VirtualBackground = VirtualBackground;
window.SimpleVirtualBackground = SimpleVirtualBackground;
