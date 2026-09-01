/**
 * =========================================================================
 * 🌌 CyberCeremony.js - 智慧排課系統 未來科技感與儀式感交互核心引擎
 * Google DeepMind High-End Futuristic Experience Suite
 * =========================================================================
 */

(function(window) {
    'use strict';

    // ---------------------------------------------------------------------
    // 1. Web Audio API 零依賴高傳真賽博音效合成器 (Cyber Synth Engine)
    // ---------------------------------------------------------------------
    class CyberAudioSynthesizer {
        constructor() {
            this.ctx = null;
            this.isMuted = localStorage.getItem('cyber_audio_muted') === 'true';
            this.masterVolume = 0.15; // 保持清爽優雅，不刺耳
            this.initialized = false;
        }

        init() {
            if (this.initialized) return;
            try {
                const AudioCtx = window.AudioContext || window.webkitAudioContext;
                if (AudioCtx) {
                    this.ctx = new AudioCtx();
                    this.initialized = true;
                }
            } catch (e) {
                console.warn("[CyberAudio] Web Audio not supported or blocked:", e);
            }
        }

        resume() {
            if (this.ctx && this.ctx.state === 'suspended') {
                this.ctx.resume();
            }
        }

        toggleMute() {
            this.isMuted = !this.isMuted;
            localStorage.setItem('cyber_audio_muted', this.isMuted);
            this.updateMuteUI();
            if (!this.isMuted) {
                this.playBoot();
            }
            return !this.isMuted;
        }

        updateMuteUI() {
            const btn = document.getElementById('cyberSoundToggleBtn');
            if (btn) {
                if (this.isMuted) {
                    btn.innerHTML = '<i class="fa-solid fa-volume-xmark"></i> <span class="d-none d-md-inline">音效: 靜音</span>';
                    btn.classList.add('muted');
                    btn.title = "點擊開啟未來科幻互動音效";
                } else {
                    btn.innerHTML = '<i class="fa-solid fa-waveform-lines fa-fade"></i> <span class="d-none d-md-inline">音效: 沉浸</span>';
                    btn.classList.remove('muted');
                    btn.title = "點擊關閉互動音效";
                }
            }
        }

        // 微輕柔量子觸感音 (滑鼠劃過按鈕/課表)
        playTick() {
            if (this.isMuted) return;
            this.init();
            this.resume();
            if (!this.ctx) return;

            try {
                const osc = this.ctx.createOscillator();
                const gain = this.ctx.createGain();
                osc.type = 'sine';
                
                const now = this.ctx.currentTime;
                osc.frequency.setValueAtTime(800, now);
                osc.frequency.exponentialRampToValueAtTime(1400, now + 0.035);

                gain.gain.setValueAtTime(0.015 * this.masterVolume, now);
                gain.gain.exponentialRampToValueAtTime(0.0001, now + 0.035);

                osc.connect(gain);
                gain.connect(this.ctx.destination);

                osc.start(now);
                osc.stop(now + 0.035);
            } catch (e) {}
        }

        // 磁吸鎖定/選取課程音 (卡片被選中)
        playSelect() {
            if (this.isMuted) return;
            this.init();
            this.resume();
            if (!this.ctx) return;

            try {
                const now = this.ctx.currentTime;
                const osc = this.ctx.createOscillator();
                const gain = this.ctx.createGain();
                osc.type = 'triangle';

                osc.frequency.setValueAtTime(440, now);
                osc.frequency.exponentialRampToValueAtTime(880, now + 0.08);

                gain.gain.setValueAtTime(0.06 * this.masterVolume, now);
                gain.gain.exponentialRampToValueAtTime(0.001, now + 0.08);

                osc.connect(gain);
                gain.connect(this.ctx.destination);

                osc.start(now);
                osc.stop(now + 0.08);
            } catch (e) {}
        }

        // 成功對調 / 動作確認和弦 (Success Harmony)
        playSuccess() {
            if (this.isMuted) return;
            this.init();
            this.resume();
            if (!this.ctx) return;

            try {
                const now = this.ctx.currentTime;
                // E Major Chord: E4, G#4, B4, E5 (未來優雅明亮)
                const freqs = [329.63, 415.30, 493.88, 659.25];
                freqs.forEach((freq, idx) => {
                    const osc = this.ctx.createOscillator();
                    const gain = this.ctx.createGain();
                    osc.type = 'sine';

                    const start = now + idx * 0.045;
                    osc.frequency.setValueAtTime(freq, start);

                    gain.gain.setValueAtTime(0.08 * this.masterVolume, start);
                    gain.gain.exponentialRampToValueAtTime(0.0001, start + 0.35);

                    osc.connect(gain);
                    gain.connect(this.ctx.destination);

                    osc.start(start);
                    osc.stop(start + 0.35);
                });
            } catch (e) {}
        }

        // 系統啟動開機音 (Crystal Boot Chime)
        playBoot() {
            if (this.isMuted) return;
            this.init();
            this.resume();
            if (!this.ctx) return;

            try {
                const now = this.ctx.currentTime;
                const notes = [523.25, 659.25, 783.99, 1046.50, 1318.51]; // C Major 9
                notes.forEach((freq, idx) => {
                    const osc = this.ctx.createOscillator();
                    const gain = this.ctx.createGain();
                    osc.type = 'sine';

                    const start = now + idx * 0.07;
                    osc.frequency.setValueAtTime(freq, start);

                    gain.gain.setValueAtTime(0.09 * this.masterVolume, start);
                    gain.gain.exponentialRampToValueAtTime(0.0001, start + 0.6);

                    osc.connect(gain);
                    gain.connect(this.ctx.destination);

                    osc.start(start);
                    osc.stop(start + 0.6);
                });
            } catch (e) {}
        }

        // 衝堂或警告警示音 (Soft Sci-fi Alert)
        playWarning() {
            if (this.isMuted) return;
            this.init();
            this.resume();
            if (!this.ctx) return;

            try {
                const now = this.ctx.currentTime;
                const osc = this.ctx.createOscillator();
                const gain = this.ctx.createGain();
                osc.type = 'sawtooth';

                osc.frequency.setValueAtTime(320, now);
                osc.frequency.linearRampToValueAtTime(240, now + 0.15);

                gain.gain.setValueAtTime(0.04 * this.masterVolume, now);
                gain.gain.exponentialRampToValueAtTime(0.001, now + 0.15);

                osc.connect(gain);
                gain.connect(this.ctx.destination);

                osc.start(now);
                osc.stop(now + 0.15);
            } catch (e) {}
        }

        // 公文蓋印 / 調課聯單生成儀式聲 (Official Seal Stamp)
        playStamp() {
            if (this.isMuted) return;
            this.init();
            this.resume();
            if (!this.ctx) return;

            try {
                const now = this.ctx.currentTime;
                const osc = this.ctx.createOscillator();
                const gain = this.ctx.createGain();
                osc.type = 'triangle';

                osc.frequency.setValueAtTime(160, now);
                osc.frequency.exponentialRampToValueAtTime(50, now + 0.18);

                gain.gain.setValueAtTime(0.12 * this.masterVolume, now);
                gain.gain.exponentialRampToValueAtTime(0.001, now + 0.18);

                osc.connect(gain);
                gain.connect(this.ctx.destination);

                osc.start(now);
                osc.stop(now + 0.18);
            } catch (e) {}
        }

        // AI 求解大獲全勝星際躍遷音 (Quantum Ascend)
        playVictory() {
            if (this.isMuted) return;
            this.init();
            this.resume();
            if (!this.ctx) return;

            try {
                const now = this.ctx.currentTime;
                const freqs = [261.63, 329.63, 392.00, 523.25, 659.25, 783.99, 1046.50];
                freqs.forEach((freq, idx) => {
                    const osc = this.ctx.createOscillator();
                    const gain = this.ctx.createGain();
                    osc.type = idx % 2 === 0 ? 'sine' : 'triangle';

                    const start = now + idx * 0.08;
                    osc.frequency.setValueAtTime(freq, start);

                    gain.gain.setValueAtTime(0.12 * this.masterVolume, start);
                    gain.gain.exponentialRampToValueAtTime(0.0001, start + 0.8);

                    osc.connect(gain);
                    gain.connect(this.ctx.destination);

                    osc.start(start);
                    osc.stop(start + 0.8);
                });
            } catch (e) {}
        }
    }

    const synth = new CyberAudioSynthesizer();
    window.CyberAudio = synth;

    // ---------------------------------------------------------------------
    // 2. 賽博光粒子與儀式感視覺引擎 (Cyber Visual & Ceremony Suite)
    // ---------------------------------------------------------------------
    class CyberVisuals {
        // 點擊光波漣漪動效
        static spawnRipple(e, customColor = 'rgba(2, 132, 199, 0.4)') {
            const ripple = document.createElement('div');
            ripple.className = 'cyber-click-ripple';
            const x = e.clientX || (e.touches && e.touches[0].clientX) || 0;
            const y = e.clientY || (e.touches && e.touches[0].clientY) || 0;
            ripple.style.left = `${x}px`;
            ripple.style.top = `${y}px`;
            ripple.style.borderColor = customColor;
            document.body.appendChild(ripple);
            setTimeout(() => ripple.remove(), 600);
        }

        // 調課成功光環迸發 (Slot Flash Pulse)
        static flashSlot(element, type = 'success') {
            if (!element) return;
            const flashClass = type === 'success' ? 'cyber-slot-flash-success' : 'cyber-slot-flash-warning';
            element.classList.add(flashClass);
            setTimeout(() => element.classList.remove(flashClass), 900);
        }

        // 浮現未來感 HUD 大字卡通知 (Cyber HUD Toast)
        static hudToast(title, desc, icon = 'fa-sparkles', type = 'info') {
            const container = document.getElementById('cyberToastHub') || (() => {
                const hub = document.createElement('div');
                hub.id = 'cyberToastHub';
                document.body.appendChild(hub);
                return hub;
            })();

            const toast = document.createElement('div');
            toast.className = `cyber-hud-toast ${type}`;
            toast.innerHTML = `
                <div class="cyber-toast-icon"><i class="fa-solid ${icon}"></i></div>
                <div class="cyber-toast-content">
                    <div class="cyber-toast-title">${title}</div>
                    <div class="cyber-toast-desc">${desc}</div>
                </div>
                <div class="cyber-toast-bar"></div>
            `;
            container.appendChild(toast);

            // 觸發音效
            if (type === 'success') synth.playSuccess();
            else if (type === 'error') synth.playWarning();
            else synth.playTick();

            setTimeout(() => {
                toast.classList.add('closing');
                setTimeout(() => toast.remove(), 350);
            }, 3600);
        }

        // 蓋印章儀式感 (調課單/公文數位標章動效)
        static triggerSealCeremony(containerElement) {
            synth.playStamp();
            const seal = document.createElement('div');
            seal.className = 'cyber-official-seal';
            seal.innerHTML = `
                <div class="seal-inner">
                    <i class="fa-solid fa-certificate"></i>
                    <span>AI 稽核通過</span>
                    <small>智慧排課數位驗證</small>
                </div>
            `;
            if (containerElement) {
                containerElement.style.position = 'relative';
                containerElement.appendChild(seal);
            }
        }
    }

    window.CyberVisuals = CyberVisuals;

    // ---------------------------------------------------------------------
    // 3. 全站互動自動掛載 (Auto-binding on Interactive Elements)
    // ---------------------------------------------------------------------
    function initGlobalCyberInteractions() {
        // 點擊漣漪
        document.addEventListener('click', (e) => {
            const target = e.target.closest('button, .action-btn, .tab-btn, .quick-btn, .interactive-slot, .dual-cell-slot, .nav-btn');
            if (target) {
                CyberVisuals.spawnRipple(e);
                synth.playTick();
            }
        }, { passive: true });

        // 懸停精緻微共振音 (使用事件委託提升性能)
        let lastHoverTime = 0;
        document.addEventListener('mouseover', (e) => {
            const btn = e.target.closest('button, .action-btn, .quick-btn, .interactive-slot, .dual-cell-slot');
            if (btn) {
                const now = Date.now();
                if (now - lastHoverTime > 75) { // 限制頻率，避免刷音
                    synth.playTick();
                    lastHoverTime = now;
                }
            }
        }, { passive: true });

        // 頂部音效控制開關掛載
        synth.updateMuteUI();

        // 首次使用者互動時啟動音頻引擎
        const activateAudioOnce = () => {
            synth.init();
            synth.resume();
            synth.playBoot();
            window.removeEventListener('click', activateAudioOnce);
            window.removeEventListener('keydown', activateAudioOnce);
        };
        window.addEventListener('click', activateAudioOnce, { once: true });
        window.addEventListener('keydown', activateAudioOnce, { once: true });
    }

    // 當 DOM 準備完成時初始化
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initGlobalCyberInteractions);
    } else {
        initGlobalCyberInteractions();
    }

})(window);
