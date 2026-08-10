// Global state
let metadata = {
    classes: [],
    teachers: [],
    classrooms: [],
    period_times: {}
};
let isManualEditMode = false;
let selectedSourceItem = null;

// DOM Elements
const searchInput = document.getElementById('searchInput');
const clearSearchBtn = document.getElementById('clearSearchBtn');
const searchDropdown = document.getElementById('searchDropdown');
const tabBtns = document.querySelectorAll('.tab-btn');
const quickSelectSection = document.getElementById('quickSelectSection');
const scheduleSection = document.getElementById('scheduleSection');
const scheduleTitle = document.getElementById('scheduleTitle');
const scheduleSubtitle = document.getElementById('scheduleSubtitle');
const scheduleBody = document.getElementById('scheduleBody');
const dbPathText = document.getElementById('dbPathText');
const backBtn = document.getElementById('backBtn');
const shareBtn = document.getElementById('shareBtn');
const printBtn = document.getElementById('printBtn');
const toast = document.getElementById('toast');
const toastText = document.getElementById('toastText');

// Print Header Elements
const printScheduleTitle = document.getElementById('printScheduleTitle');
const printTutorInfo = document.getElementById('printTutorInfo');
const printDateSpan = document.getElementById('printDateSpan');

// Initial Setup
document.addEventListener('DOMContentLoaded', () => {
    fetchMetadata();
    setupEventListeners();
    handleHashChange();

    // Global ESC key to close any open modal
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            document.querySelectorAll('.modal-overlay').forEach(m => {
                if (m.style.display !== 'none') {
                    m.style.display = 'none';
                }
            });
        }
    });

    // Close modal when clicking on backdrop overlay outside modal content
    document.querySelectorAll('.modal-overlay').forEach(modal => {
        modal.addEventListener('click', (e) => {
            if (e.target === modal) {
                modal.style.display = 'none';
            }
        });
    });
});

// Event Listeners Setup
function setupEventListeners() {
    // Hash Routing
    window.addEventListener('hashchange', handleHashChange);

    // Back Button
    backBtn.addEventListener('click', () => {
        window.location.hash = '';
    });

    // Share Button
    shareBtn.addEventListener('click', copyShareLink);

    // Print Button
    printBtn.addEventListener('click', () => {
        // Set current date for printing
        const today = new Date();
        printDateSpan.textContent = `${today.getFullYear()}/${today.getMonth() + 1}/${today.getDate()}`;
        window.print();
    });

    // Tab buttons for quick selection
    tabBtns.forEach(btn => {
        btn.addEventListener('click', (e) => {
            tabBtns.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            
            const activeTab = btn.getAttribute('data-tab');
            switchQuickSelectTab(activeTab);
        });
    });

    // Search bar functionality
    searchInput.addEventListener('input', handleSearchInput);
    searchInput.addEventListener('focus', () => {
        if (searchInput.value.trim().length > 0) {
            searchDropdown.style.display = 'block';
        }
    });

    // Clear Search Button
    clearSearchBtn.addEventListener('click', () => {
        searchInput.value = '';
        clearSearchBtn.style.display = 'none';
        searchDropdown.style.display = 'none';
        searchInput.focus();
    });

    // Close dropdown on click outside
    document.addEventListener('click', (e) => {
        if (!searchInput.contains(e.target) && !searchDropdown.contains(e.target)) {
            searchDropdown.style.display = 'none';
        }
    });

    // Manual Edit Button
    const manualEditToggleBtn = document.getElementById('manualEditToggleBtn');
    if (manualEditToggleBtn) {
        manualEditToggleBtn.addEventListener('click', () => {
            isManualEditMode = !isManualEditMode;
            if (isManualEditMode) {
                manualEditToggleBtn.innerHTML = '<i class="fa-solid fa-xmark"></i> 退出手調';
                manualEditToggleBtn.style.background = 'rgba(239, 68, 68, 0.15)';
                manualEditToggleBtn.style.borderColor = 'rgba(239, 68, 68, 0.4)';
                manualEditToggleBtn.style.color = '#ef4444';
                showToast("已開啟手排微調模式。點擊課表內的課程以進行調整。");
                document.getElementById('scheduleTable').classList.add('edit-mode');
            } else {
                manualEditToggleBtn.innerHTML = '<i class="fa-solid fa-screwdriver-wrench"></i> 手手調課';
                manualEditToggleBtn.style.background = 'rgba(6, 182, 212, 0.15)';
                manualEditToggleBtn.style.borderColor = 'rgba(6, 182, 212, 0.3)';
                manualEditToggleBtn.style.color = '#06b6d4';
                document.getElementById('scheduleTable').classList.remove('edit-mode');
                resetManualEditState();
                handleHashChange();
            }
        });
    }

    setupSettingsPanel();
    setupSolverPanel();
}

// Fetch Metadata (Classes, Teachers, Rooms)
async function fetchMetadata() {
    try {
        const response = await fetch('/api/metadata');
        const data = await response.json();
        
        if (data.error) {
            console.error("API error:", data.error);
            dbPathText.textContent = "資料庫載入失敗";
            return;
        }

        metadata = data;
        
        // Show database name/path in badge
        if (data.dbf_dir) {
            const parts = data.dbf_dir.split(/[\\/]/);
            const dbfFolder = parts.find(p => p.toLowerCase().startsWith('spv') && p.toLowerCase().endsWith('.wdb'));
            dbPathText.textContent = dbfFolder || "SPV2000 資料庫";
        }

        renderQuickSelectGrids();
    } catch (e) {
        console.error("Fetch metadata failed:", e);
        dbPathText.textContent = "連線失敗";
    }
}

// Render Quick Select grids
function renderQuickSelectGrids() {
    const highSchoolGrid = document.getElementById('highSchoolGrid');
    const juniorHighGrid = document.getElementById('juniorHighGrid');
    const teachersGrid = document.getElementById('teachersGrid');
    const roomsGrid = document.getElementById('roomsGrid');

    highSchoolGrid.innerHTML = '';
    juniorHighGrid.innerHTML = '';
    teachersGrid.innerHTML = '';
    roomsGrid.innerHTML = '';

    // 1. Classes
    metadata.classes.forEach(cls => {
        const item = document.createElement('a');
        item.href = `#class/${cls.code}`;
        item.className = 'grid-item';
        item.innerHTML = `${cls.name}<span class="sub-label">${cls.tutor || '無導師'}</span>`;
        
        // Junior high vs High school grouping
        const firstChar = cls.code.charAt(0);
        if (firstChar === '1' || firstChar === '2' || firstChar === '3') {
            juniorHighGrid.appendChild(item);
        } else {
            highSchoolGrid.appendChild(item);
        }
    });

    // 2. Teachers
    metadata.teachers.forEach(t => {
        const item = document.createElement('a');
        item.href = `#teacher/${t.code}`;
        item.className = 'grid-item';
        item.innerHTML = `${t.name}<span class="sub-label">${t.role || '教師'}</span>`;
        teachersGrid.appendChild(item);
    });

    // 3. Classrooms
    metadata.classrooms.forEach(room => {
        const item = document.createElement('a');
        item.href = `#room/${room.code}`;
        item.className = 'grid-item';
        item.innerHTML = `${room.name}`;
        roomsGrid.appendChild(item);
    });
}

// Switch between Quick Select Tab views
function switchQuickSelectTab(tabName) {
    document.getElementById('classQuickContainer').classList.remove('active');
    document.getElementById('teacherQuickContainer').classList.remove('active');
    document.getElementById('roomQuickContainer').classList.remove('active');

    if (tabName === 'class') {
        document.getElementById('classQuickContainer').classList.add('active');
    } else if (tabName === 'teacher') {
        document.getElementById('teacherQuickContainer').classList.add('active');
    } else if (tabName === 'room') {
        document.getElementById('roomQuickContainer').classList.add('active');
    }
}

// Handle Search bar autocomplete
function handleSearchInput(e) {
    const query = e.target.value.trim().toLowerCase();
    
    if (query.length === 0) {
        clearSearchBtn.style.display = 'none';
        searchDropdown.style.display = 'none';
        return;
    }

    clearSearchBtn.style.display = 'block';
    
    // Filter results
    const matches = [];

    // Filter classes
    metadata.classes.forEach(cls => {
        if (cls.name.toLowerCase().includes(query) || cls.code.toLowerCase().includes(query) || (cls.tutor && cls.tutor.toLowerCase().includes(query))) {
            matches.push({ type: 'class', label: `${cls.name} (班級)`, code: cls.code, sub: cls.tutor ? `導師: ${cls.tutor}` : '' });
        }
    });

    // Filter teachers
    metadata.teachers.forEach(t => {
        if (t.name.toLowerCase().includes(query) || t.code.toLowerCase().includes(query) || (t.role && t.role.toLowerCase().includes(query))) {
            matches.push({ type: 'teacher', label: `${t.name} (教師)`, code: t.code, sub: t.role || '' });
        }
    });

    // Filter classrooms
    metadata.classrooms.forEach(room => {
        if (room.name.toLowerCase().includes(query) || room.code.toLowerCase().includes(query)) {
            matches.push({ type: 'room', label: `${room.name} (教室)`, code: room.code, sub: '' });
        }
    });

    // Render Dropdown
    searchDropdown.innerHTML = '';
    if (matches.length === 0) {
        const emptyItem = document.createElement('div');
        emptyItem.className = 'dropdown-item';
        emptyItem.style.color = 'var(--text-secondary)';
        emptyItem.textContent = '找不到符合的結果';
        searchDropdown.appendChild(emptyItem);
    } else {
        // Cap results at 10
        matches.slice(0, 10).forEach(match => {
            const item = document.createElement('div');
            item.className = 'dropdown-item';
            item.innerHTML = `
                <div>
                    <div><strong>${match.label}</strong></div>
                    ${match.sub ? `<span style="font-size:0.75rem; color:var(--text-secondary);">${match.sub}</span>` : ''}
                </div>
                <span class="item-type">${match.type === 'class' ? '班級' : match.type === 'teacher' ? '教師' : '教室'}</span>
            `;
            item.addEventListener('click', () => {
                window.location.hash = `#${match.type}/${match.code}`;
                searchInput.value = '';
                clearSearchBtn.style.display = 'none';
                searchDropdown.style.display = 'none';
            });
            searchDropdown.appendChild(item);
        });
    }

    searchDropdown.style.display = 'block';
}

// Handle Routing via Hash change
function handleHashChange() {
    const hash = window.location.hash;
    
    if (!hash || hash === '#') {
        // Show Selection view
        quickSelectSection.style.display = 'block';
        scheduleSection.style.display = 'none';
        document.title = "土城高中課表查詢系統";
        return;
    }

    const match = hash.match(/^#(class|teacher|room)\/([a-zA-Z0-9%_-]+)$/);
    if (!match) {
        window.location.hash = '';
        return;
    }

    const type = match[1];
    const code = decodeURIComponent(match[2]);

    loadSchedule(type, code);
}

// Load schedule for specific class, teacher, or classroom
async function loadSchedule(type, code) {
    // Show Loading state
    quickSelectSection.style.display = 'none';
    scheduleSection.style.display = 'block';
    scheduleTitle.textContent = "讀取課表中...";
    scheduleSubtitle.textContent = "";
    scheduleBody.innerHTML = '<tr><td colspan="6" style="padding: 3rem; text-align: center;"><i class="fa-solid fa-spinner fa-spin fa-2xl" style="color:var(--primary);"></i></td></tr>';

    try {
        const response = await fetch(`/api/schedule/${type}/${code}`);
        const slots = await response.json();
        
        if (slots.error) {
            scheduleTitle.textContent = "載入課表失敗";
            scheduleSubtitle.textContent = slots.error;
            scheduleBody.innerHTML = '';
            return;
        }

        renderScheduleGrid(type, code, slots);
    } catch (e) {
        console.error("Load schedule failed:", e);
        scheduleTitle.textContent = "連線失敗";
        scheduleBody.innerHTML = '';
    }
}

// Render schedule grid table
function renderScheduleGrid(type, code, slots) {
    // 1. Set Title & Subtitle based on query type
    let title = "";
    let subtitle = "";

    if (type === 'class') {
        const cls = metadata.classes.find(c => c.code === code);
        title = `${cls ? cls.name : code} 班級課表`;
        subtitle = cls && cls.tutor ? `導師：${cls.tutor}` : "無導師設定";
        printScheduleTitle.textContent = title;
        printTutorInfo.textContent = subtitle;
        document.title = `${cls ? cls.name : code} 課表 - 土城高中課表查詢`;
    } else if (type === 'teacher') {
        const t = metadata.teachers.find(x => x.code === code);
        title = `${t ? t.name : code} 老師課表`;
        subtitle = t && t.role ? `職務：${t.role}` : "";
        printScheduleTitle.textContent = title;
        printTutorInfo.textContent = subtitle;
        document.title = `${t ? t.name : code} 老師課表 - 土城高中課表查詢`;
    } else if (type === 'room') {
        const room = metadata.classrooms.find(r => r.code === code);
        title = `${room ? room.name : code} 教室課表`;
        subtitle = `專科教室課表`;
        printScheduleTitle.textContent = title;
        printTutorInfo.textContent = subtitle;
        document.title = `${room ? room.name : code} 教室課表 - 土城高中課表查詢`;
    }

    scheduleTitle.textContent = title;
    scheduleSubtitle.textContent = subtitle;

    // 2. Initialize 5x8 grid array (5 days, 8 periods)
    // grid[p][d] represents period p (1-8) and day d (Monday-Friday, indices 0-4)
    const grid = Array(8).fill(null).map(() => Array(5).fill(null).map(() => []));

    slots.forEach(slot => {
        const d = parseInt(slot.day);
        const p = parseInt(slot.period);
        
        // Ensure values are within normal school week grid
        if (d >= 1 && d <= 5 && p >= 1 && p <= 8) {
            grid[p-1][d-1].push(slot);
        }
    });

    // 3. Render rows
    scheduleBody.innerHTML = '';
    
    for (let p = 1; p <= 8; p++) {
        const row = document.createElement('tr');
        
        // Time / Period label column
        const timeData = metadata.period_times[p.toString()] || { name: `第${p}節`, time: "" };
        const timeCell = document.createElement('td');
        timeCell.className = 'time-col';
        timeCell.innerHTML = `<span class="period-name">${timeData.name}</span><span class="period-time">${timeData.time}</span>`;
        row.appendChild(timeCell);

        // Day columns (Mon-Fri)
        for (let d = 1; d <= 5; d++) {
            const cell = document.createElement('td');
            const lessons = grid[p-1][d-1];
            
            cell.classList.add('interactive-slot');
            cell.dataset.day = d;
            cell.dataset.period = p;
            
            cell.addEventListener('click', (e) => {
                if (!isManualEditMode || !selectedSourceItem) return;
                if (e.target.closest('.lesson-block')) return;
                
                if (cell.classList.contains('slot-feasible') || cell.classList.contains('slot-soft-conflict')) {
                    executeSwap(selectedSourceItem.id, d, p, null);
                }
            });
            
            if (lessons.length === 0) {
                cell.innerHTML = '<div class="schedule-cell"></div>';
            } else {
                const cellContainer = document.createElement('div');
                cellContainer.className = 'schedule-cell has-lesson';
                
                // If there are multiple lessons (e.g. odd/even week alternations)
                lessons.forEach((lesson, index) => {
                    const lessonDiv = document.createElement('div');
                    lessonDiv.style.width = '100%';
                    lessonDiv.style.display = 'flex';
                    lessonDiv.style.flexDirection = 'column';
                    lessonDiv.style.alignItems = 'center';
                    lessonDiv.style.gap = '2px';
                    
                    lessonDiv.className = 'lesson-block';
                    lessonDiv.dataset.id = lesson.id;
                    
                    lessonDiv.addEventListener('click', (e) => {
                        if (!isManualEditMode) return;
                        e.preventDefault();
                        e.stopPropagation();
                        
                        if (selectedSourceItem && selectedSourceItem.id === lesson.id) {
                            resetManualEditState();
                            return;
                        }
                        
                        if (selectedSourceItem && (cell.classList.contains('slot-feasible') || cell.classList.contains('slot-soft-conflict'))) {
                            executeSwap(selectedSourceItem.id, d, p, lesson.id);
                            return;
                        }
                        
                        // Select as source
                        resetManualEditState();
                        selectedSourceItem = lesson;
                        cellContainer.classList.add('source-selected');
                        highlightSlots(lesson.id);
                    });
                    
                    if (index > 0) {
                        lessonDiv.style.borderTop = '1px dashed rgba(255,255,255,0.1)';
                        lessonDiv.style.paddingTop = '6px';
                        lessonDiv.style.marginTop = '6px';
                    }

                    let mainText = lesson.subject_name;
                    let targetLink = '';
                    let roomLink = '';

                    if (type === 'class') {
                        // Class view: link to teacher and classroom
                        targetLink = lesson.teacher_code ? `<a href="#teacher/${lesson.teacher_code}" class="meta-link">${lesson.teacher_name}</a>` : '';
                        roomLink = lesson.room_code ? `<a href="#room/${lesson.room_code}" class="room-lbl meta-link"><i class="fa-solid fa-location-dot"></i> ${lesson.room_name}</a>` : '';
                    } else if (type === 'teacher') {
                        // Teacher view: link to class and classroom
                        targetLink = lesson.class_code ? `<a href="#class/${lesson.class_code}" class="meta-link">${lesson.class_name}</a>` : '';
                        roomLink = lesson.room_code ? `<a href="#room/${lesson.room_code}" class="room-lbl meta-link"><i class="fa-solid fa-location-dot"></i> ${lesson.room_name}</a>` : '';
                    } else if (type === 'room') {
                        // Room view: link to class and teacher
                        targetLink = lesson.class_code ? `<a href="#class/${lesson.class_code}" class="meta-link">${lesson.class_name}</a>` : '';
                        roomLink = lesson.teacher_code ? `<span class="room-lbl" style="font-size:0.85rem;"><a href="#teacher/${lesson.teacher_code}" class="meta-link">${lesson.teacher_name}</a></span>` : '';
                    }

                    // Week Mode Banner
                    let badge = '';
                    if (lesson.week_mode === 1) {
                        badge = '<span class="week-badge odd">單</span>';
                    } else if (lesson.week_mode === 2) {
                        badge = '<span class="week-badge even">雙</span>';
                    }

                    lessonDiv.innerHTML = `
                        <span class="subject-name">${mainText}</span>
                        ${targetLink}
                        ${roomLink}
                        ${badge}
                    `;
                    
                    cellContainer.appendChild(lessonDiv);
                });

                cell.appendChild(cellContainer);
            }
            row.appendChild(cell);
        }
        
        scheduleBody.appendChild(row);
    }
}

// Share function
function copyShareLink() {
    const link = window.location.href;
    navigator.clipboard.writeText(link).then(() => {
        showToast("已成功複製分享連結！");
    }).catch(err => {
        console.error("Copy failed:", err);
        showToast("複製失敗，請手動複製網址列連結。");
    });
}

// Show toast alert
function showToast(text) {
    toastText.textContent = text;
    toast.classList.add('show');
    setTimeout(() => {
        toast.classList.remove('show');
    }, 2500);
}

// AI Solver Modal and Controller Logic
function setupSolverPanel() {
    const solverPanelBtn = document.getElementById('solverPanelBtn');
    const solverModal = document.getElementById('solverModal');
    const closeSolverBtn = document.getElementById('closeSolverBtn');
    const runSolverBtn = document.getElementById('runSolverBtn');
    const validateSolverBtn = document.getElementById('validateSolverBtn');
    const downloadSolvedBtn = document.getElementById('downloadSolvedBtn');
    const solverConsole = document.getElementById('solverConsole');
    const clearConsoleBtn = document.getElementById('clearConsoleBtn');

    if (!solverPanelBtn || !solverModal) return;

    // Toggle Modal visibility
    solverPanelBtn.addEventListener('click', () => {
        solverModal.style.display = 'flex';
    });

    closeSolverBtn.addEventListener('click', () => {
        solverModal.style.display = 'none';
    });

    // Close when clicking overlay backdrop
    solverModal.addEventListener('click', (e) => {
        if (e.target === solverModal) {
            solverModal.style.display = 'none';
        }
    });

    // Clear console terminal
    clearConsoleBtn.addEventListener('click', () => {
        solverConsole.innerHTML = '<p class="system-msg">日誌已清除。請執行排課或驗證。</p>';
    });

    // Reset Schedule
    const resetScheduleBtn = document.getElementById('resetScheduleBtn');
    if (resetScheduleBtn) {
        resetScheduleBtn.addEventListener('click', async () => {
            if (!confirm("您確定要將全校課表清零重置嗎？此動作將清除過往的所有課表與手動鎖定紀錄。")) return;
            
            solverConsole.innerHTML = '<p class="system-msg"><i class="fa-solid fa-circle-notch console-spinner"></i> 正在執行全校課表清零重置...</p>';
            try {
                const response = await fetch('/api/reset-schedule', { method: 'POST' });
                const res = await response.json();
                if (res.status === 'success') {
                    solverConsole.innerHTML = `<p class="success-msg"><i class="fa-solid fa-circle-check"></i> ${res.message}</p>`;
                    showToast(res.message);
                    if (window.location.hash) {
                        handleHashChange();
                    }
                    fetchMetadata();
                } else {
                    solverConsole.innerHTML = `<p class="error-msg"><i class="fa-solid fa-circle-xmark"></i> 清零失敗：${res.message}</p>`;
                }
            } catch (e) {
                console.error("Reset schedule failed:", e);
                solverConsole.innerHTML = '<p class="error-msg"><i class="fa-solid fa-circle-xmark"></i> 連線伺服器重置失敗。</p>';
            }
        });
    }

    // Run solver
    runSolverBtn.addEventListener('click', async () => {
        // Disable buttons
        runSolverBtn.disabled = true;
        validateSolverBtn.disabled = true;
        if (downloadSolvedBtn) {
            downloadSolvedBtn.style.pointerEvents = 'none';
            downloadSolvedBtn.style.opacity = '0.5';
        }
        
        // Setup console loading state
        solverConsole.innerHTML = `
            <p class="system-msg"><i class="fa-solid fa-circle-notch console-spinner"></i> [1/2] 正在連結伺服器，載入最新排課參數與限制條件...</p>
        `;

        try {
            await new Promise(resolve => setTimeout(resolve, 800));
            solverConsole.innerHTML += `<p class="info-msg">[2/2] 正在啟動 Google OR-Tools CP-SAT 高階排課最佳化求解器...</p>`;
            solverConsole.scrollTop = solverConsole.scrollHeight;

            const response = await fetch(`/api/run-solver?t=${Date.now()}`);
            const data = await response.json();

            if (data.status === 'success') {
                if (data.logs && data.logs.length > 0) {
                    for (const logLine of data.logs) {
                        solverConsole.innerHTML += `<p class="system-msg">> ${logLine}</p>`;
                        solverConsole.scrollTop = solverConsole.scrollHeight;
                        await new Promise(resolve => setTimeout(resolve, 150));
                    }
                }
                
                solverConsole.innerHTML += `<p class="success-msg"><i class="fa-solid fa-circle-check"></i> [成功] ${data.message || '排課順利完成，已成功產生最佳化課表 Excel 檔案！'}</p>`;
                showToast("AI 自動排課成功！");
                
                if (window.location.hash) {
                    handleHashChange();
                }
                fetchMetadata();
            } else {
                solverConsole.innerHTML += `<p class="error-msg"><i class="fa-solid fa-triangle-exclamation"></i> [錯誤] ${data.message || '排課求解失敗，請檢查限制條件是否互斥。'}</p>`;
                if (data.logs && data.logs.length > 0) {
                    for (const logLine of data.logs) {
                        solverConsole.innerHTML += `<p class="system-msg" style="color: #fda4af;">> ${logLine}</p>`;
                    }
                }
            }
        } catch (error) {
            console.error(error);
            solverConsole.innerHTML += `<p class="error-msg"><i class="fa-solid fa-circle-xmark"></i> [錯誤] 連線伺服器時發生異常，無法啟動排課模組。</p>`;
        } finally {
            runSolverBtn.disabled = false;
            validateSolverBtn.disabled = false;
            if (downloadSolvedBtn) {
                downloadSolvedBtn.style.pointerEvents = 'auto';
                downloadSolvedBtn.style.opacity = '1';
            }
            solverConsole.scrollTop = solverConsole.scrollHeight;
        }
    });

    // Validate solver
    validateSolverBtn.addEventListener('click', async () => {
        runSolverBtn.disabled = true;
        validateSolverBtn.disabled = true;
        if (downloadSolvedBtn) {
            downloadSolvedBtn.style.pointerEvents = 'none';
            downloadSolvedBtn.style.opacity = '0.5';
        }

        solverConsole.innerHTML = `
            <p class="system-msg"><i class="fa-solid fa-circle-notch console-spinner"></i> 正在執行高精準度衝堂衝突雙向驗證...</p>
        `;

        try {
            await new Promise(resolve => setTimeout(resolve, 800));
            const response = await fetch(`/api/validate-solver?t=${Date.now()}`);
            const data = await response.json();

            if (data.status === 'success') {
                solverConsole.innerHTML = `
                    <p class="success-msg"><i class="fa-solid fa-shield-check"></i> 課表衝突雙向驗證完成！</p>
                    <p class="info-msg">> 軟性教師限制衝突數：${data.teacher_violations_soft || 0} 節次</p>
                    <p class="info-msg">> 軟性科目分散衝突數：${data.class_sub_violations_hard || 0} 節次</p>
                    <p class="success-msg">> 實質衝堂（Hard Conflicts）：${data.hard_conflicts || 0} 個</p>
                `;
                
                if (data.details && data.details.length > 0) {
                    solverConsole.innerHTML += `<p class="system-msg" style="border-top:1px dashed var(--border-color); margin-top:8px; padding-top:8px;">[系統比對明細] 以下為系統偵測之所有排課細項狀態：</p>`;
                    for (const detail of data.details) {
                        let color = '#cbd5e1';
                        if (detail.includes('[Teacher Conflict]') || detail.includes('[Class Conflict]')) {
                            // Standard split check
                            if (detail.includes('閩南語文') || detail.includes('原民語') || detail.includes('臺灣手語') || detail.includes('自主學習') || detail.includes('週期課程') || detail.includes('專題課程') || detail.includes('探究')) {
                                color = '#cbd5e1'; // Gray for standard split/combined classes
                            } else {
                                color = '#f87171'; // Red for unexpected real conflicts
                            }
                        }
                        solverConsole.innerHTML += `<p style="color: ${color}; font-size: 0.8rem; margin-bottom: 2px;">• ${detail}</p>`;
                    }
                }
                
                showToast("課表驗證完成！");
            } else {
                solverConsole.innerHTML += `<p class="error-msg"><i class="fa-solid fa-circle-xmark"></i> 驗證失敗：${data.message}</p>`;
            }
        } catch (error) {
            console.error(error);
            solverConsole.innerHTML += `<p class="error-msg"><i class="fa-solid fa-circle-xmark"></i> 連線伺服器驗證模組失敗。</p>`;
        } finally {
            runSolverBtn.disabled = false;
            validateSolverBtn.disabled = false;
            if (downloadSolvedBtn) {
                downloadSolvedBtn.style.pointerEvents = 'auto';
                downloadSolvedBtn.style.opacity = '1';
            }
            solverConsole.scrollTop = solverConsole.scrollHeight;
        }
    });
}

function resetManualEditState() {
    selectedSourceItem = null;
    const cells = document.querySelectorAll('#scheduleTable td');
    cells.forEach(c => {
        c.classList.remove('slot-feasible', 'slot-soft-conflict', 'slot-forbidden', 'slot-current');
    });
    const divs = document.querySelectorAll('.schedule-cell');
    divs.forEach(d => d.classList.remove('source-selected'));
}

async function highlightSlots(itemId) {
    try {
        const response = await fetch(`/api/check-swap-slots/${itemId}`);
        const data = await response.json();
        
        if (data.status === 'error') {
            showToast(data.message);
            return;
        }
        
        if (data.item && data.item.consecutive_hint) {
            showToast(data.item.consecutive_hint);
        }
        
        const slots = data.slots;
        for (const slotKey in slots) {
            const parts = slotKey.split('-');
            const d = parts[0];
            const p = parts[1];
            
            const cell = document.querySelector(`#scheduleTable td[data-day="${d}"][data-period="${p}"]`);
            if (cell) {
                cell.classList.remove('slot-feasible', 'slot-soft-conflict', 'slot-forbidden', 'slot-current');
                const status = slots[slotKey].status;
                if (status === 'feasible') {
                    cell.classList.add('slot-feasible');
                } else if (status === 'soft_conflict') {
                    cell.classList.add('slot-soft-conflict');
                } else if (status === 'forbidden') {
                    cell.classList.add('slot-forbidden');
                } else if (status === 'current') {
                    cell.classList.add('slot-current');
                }
                
                cell.title = slots[slotKey].message;
            }
        }
    } catch (e) {
        console.error("Highlight slots failed:", e);
    }
}

async function executeSwap(sourceId, targetDay, targetPeriod, targetId) {
    let confirmMsg = "您確定要將此課程調整至該時段嗎？";
    if (targetId !== null) {
        confirmMsg = "目標時段已排課，您確定要將兩門課程對調嗎？";
    }
    
    if (!confirm(confirmMsg)) return;
    
    try {
        const response = await fetch('/api/execute-swap', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                source_id: sourceId,
                target_day: targetDay,
                target_period: targetPeriod,
                target_id: targetId
            })
        });
        
        const res = await response.json();
        if (res.status === 'success') {
            isManualEditMode = false;
            const btn = document.getElementById('manualEditToggleBtn');
            if (btn) {
                btn.innerHTML = '<i class="fa-solid fa-screwdriver-wrench"></i> 手手調課';
                btn.style.background = 'rgba(6, 182, 212, 0.15)';
                btn.style.borderColor = 'rgba(6, 182, 212, 0.3)';
                btn.style.color = '#06b6d4';
            }
            document.getElementById('scheduleTable').classList.remove('edit-mode');
            resetManualEditState();
            showToast(res.message);
            handleHashChange();
        } else {
            showToast("調整失敗：" + res.message);
        }
    } catch (e) {
        console.error("Execute swap failed:", e);
        showToast("伺服器連線異常，調課失敗。");
    }
}

// Settings and Rules Panel Logic
let configRulesData = {
    no_teach: {},
    no_sub: {},
    weights: {}
};

function setupSettingsPanel() {
    const settingsModalBtn = document.getElementById('settingsModalBtn');
    const settingsModal = document.getElementById('settingsModal');
    const closeSettingsBtn = document.getElementById('closeSettingsBtn');

    if (!settingsModalBtn || !settingsModal) return;

    settingsModalBtn.addEventListener('click', () => {
        settingsModal.style.display = 'flex';
        initSettingsModal();
        switchRuleTab('teacher');
    });

    closeSettingsBtn.addEventListener('click', () => {
        settingsModal.style.display = 'none';
    });

    settingsModal.addEventListener('click', (e) => {
        if (e.target === settingsModal) {
            settingsModal.style.display = 'none';
        }
    });

    // Rule Tabs
    const tabRuleTeacherBtn = document.getElementById('tabRuleTeacherBtn');
    const tabRuleSubBtn = document.getElementById('tabRuleSubBtn');
    const tabRuleWeightsBtn = document.getElementById('tabRuleWeightsBtn');
    const tabRuleAssignBtn = document.getElementById('tabRuleAssignBtn');
    const tabRuleCatalogBtn = document.getElementById('tabRuleCatalogBtn');
    const tabRuleRestoreBtn = document.getElementById('tabRuleRestoreBtn');
    const ruleTabTeacher = document.getElementById('ruleTabTeacher');
    const ruleTabSub = document.getElementById('ruleTabSub');
    const ruleTabWeights = document.getElementById('ruleTabWeights');
    const ruleTabAssign = document.getElementById('ruleTabAssign');
    const ruleTabCatalog = document.getElementById('ruleTabCatalog');
    const ruleTabRestore = document.getElementById('ruleTabRestore');

    function switchRuleTab(tabName) {
        [tabRuleTeacherBtn, tabRuleSubBtn, tabRuleWeightsBtn, tabRuleAssignBtn, tabRuleCatalogBtn, tabRuleRestoreBtn].forEach(b => {
            if (b) {
                b.classList.remove('active');
                b.style.background = 'transparent';
                b.style.color = 'var(--text-secondary)';
            }
        });
        [ruleTabTeacher, ruleTabSub, ruleTabWeights, ruleTabAssign, ruleTabCatalog, ruleTabRestore].forEach(c => {
            if (c) c.style.display = 'none';
        });

        if (tabName === 'teacher') {
            tabRuleTeacherBtn.classList.add('active');
            tabRuleTeacherBtn.style.background = 'rgba(99, 102, 241, 0.2)';
            tabRuleTeacherBtn.style.color = '#818cf8';
            ruleTabTeacher.style.display = 'block';
        } else if (tabName === 'sub') {
            tabRuleSubBtn.classList.add('active');
            tabRuleSubBtn.style.background = 'rgba(99, 102, 241, 0.2)';
            tabRuleSubBtn.style.color = '#818cf8';
            ruleTabSub.style.display = 'block';
        } else if (tabName === 'weights') {
            tabRuleWeightsBtn.classList.add('active');
            tabRuleWeightsBtn.style.background = 'rgba(99, 102, 241, 0.2)';
            tabRuleWeightsBtn.style.color = '#818cf8';
            ruleTabWeights.style.display = 'block';
        } else if (tabName === 'assign') {
            tabRuleAssignBtn.classList.add('active');
            tabRuleAssignBtn.style.background = 'rgba(99, 102, 241, 0.2)';
            tabRuleAssignBtn.style.color = '#818cf8';
            ruleTabAssign.style.display = 'block';
            loadCourseAssignments();
        } else if (tabName === 'catalog') {
            tabRuleCatalogBtn.classList.add('active');
            tabRuleCatalogBtn.style.background = 'rgba(99, 102, 241, 0.2)';
            tabRuleCatalogBtn.style.color = '#818cf8';
            ruleTabCatalog.style.display = 'block';
            loadSubjectCatalog();
        } else if (tabName === 'restore') {
            tabRuleRestoreBtn.classList.add('active');
            tabRuleRestoreBtn.style.background = 'rgba(99, 102, 241, 0.2)';
            tabRuleRestoreBtn.style.color = '#818cf8';
            ruleTabRestore.style.display = 'block';
            loadRestorePoints();
        }
    }

    if (tabRuleTeacherBtn) tabRuleTeacherBtn.addEventListener('click', () => switchRuleTab('teacher'));
    if (tabRuleSubBtn) tabRuleSubBtn.addEventListener('click', () => switchRuleTab('sub'));
    if (tabRuleWeightsBtn) tabRuleWeightsBtn.addEventListener('click', () => switchRuleTab('weights'));
    if (tabRuleAssignBtn) tabRuleAssignBtn.addEventListener('click', () => switchRuleTab('assign'));
    if (tabRuleCatalogBtn) tabRuleCatalogBtn.addEventListener('click', () => switchRuleTab('catalog'));
    if (tabRuleRestoreBtn) tabRuleRestoreBtn.addEventListener('click', () => switchRuleTab('restore'));

    // Range Sliders
    const weightConsecutive = document.getElementById('weightConsecutive');
    const weightNoTeach = document.getElementById('weightNoTeach');
    const weightNoSub = document.getElementById('weightNoSub');
    const weightSpreading = document.getElementById('weightSpreading');

    if (weightConsecutive) weightConsecutive.addEventListener('input', (e) => document.getElementById('weightConsecutiveVal').textContent = e.target.value);
    if (weightNoTeach) weightNoTeach.addEventListener('input', (e) => document.getElementById('weightNoTeachVal').textContent = e.target.value);
    if (weightNoSub) weightNoSub.addEventListener('input', (e) => document.getElementById('weightNoSubVal').textContent = e.target.value);
    if (weightSpreading) weightSpreading.addEventListener('input', (e) => document.getElementById('weightSpreadingVal').textContent = e.target.value);

    // Render 5x8 Grid Tables
    renderRuleGrid('teacherRuleGridBody');
    renderRuleGrid('subRuleGridBody');

    // Teacher select change
    const teacherSelectRule = document.getElementById('teacherSelectRule');
    if (teacherSelectRule) {
        teacherSelectRule.addEventListener('change', () => {
            const tc = teacherSelectRule.value;
            const blockedSlots = configRulesData.no_teach[tc] || [];
            updateGridSlots('teacherRuleGridBody', blockedSlots);
        });
    }

    // Save Teacher Rule
    const saveTeacherRuleBtn = document.getElementById('saveTeacherRuleBtn');
    if (saveTeacherRuleBtn) {
        saveTeacherRuleBtn.addEventListener('click', async () => {
            const tc = teacherSelectRule.value;
            if (!tc) {
                showToast("請先選擇教師！");
                return;
            }
            const activeSlots = getGridActiveSlots('teacherRuleGridBody');
            try {
                const resp = await fetch('/api/config-rules/save-no-teach', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ teacher_code: tc, slots: activeSlots })
                });
                const res = await resp.json();
                if (res.status === 'success') {
                    configRulesData.no_teach[tc] = activeSlots;
                    showToast("教師不排課時段已成功儲存！");
                } else {
                    showToast("儲存失敗：" + res.message);
                }
            } catch (e) {
                showToast("伺服器連線異常。");
            }
        });
    }

    // Clear Teacher Rule
    const clearTeacherRuleBtn = document.getElementById('clearTeacherRuleBtn');
    if (clearTeacherRuleBtn) {
        clearTeacherRuleBtn.addEventListener('click', () => {
            updateGridSlots('teacherRuleGridBody', []);
        });
    }

    // Sub select change
    const classSelectRule = document.getElementById('classSelectRule');
    const subSelectRule = document.getElementById('subSelectRule');
    function updateSubGrid() {
        if (!classSelectRule || !subSelectRule) return;
        const cc = classSelectRule.value;
        const sc = subSelectRule.value;
        if (cc && sc) {
            const key = `${cc}|${sc}`;
            const blockedSlots = configRulesData.no_sub[key] || [];
            updateGridSlots('subRuleGridBody', blockedSlots);
        }
    }
    if (classSelectRule) classSelectRule.addEventListener('change', updateSubGrid);
    if (subSelectRule) subSelectRule.addEventListener('change', updateSubGrid);

    // Save Sub Rule
    const saveSubRuleBtn = document.getElementById('saveSubRuleBtn');
    if (saveSubRuleBtn) {
        saveSubRuleBtn.addEventListener('click', async () => {
            const cc = classSelectRule.value;
            const sc = subSelectRule.value;
            if (!cc || !sc) {
                showToast("請選擇班級與科目！");
                return;
            }
            const activeSlots = getGridActiveSlots('subRuleGridBody');
            try {
                const resp = await fetch('/api/config-rules/save-no-sub', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ class_code: cc, subject_code: sc, slots: activeSlots })
                });
                const res = await resp.json();
                if (res.status === 'success') {
                    const key = `${cc}|${sc}`;
                    configRulesData.no_sub[key] = activeSlots;
                    showToast("科目限制時段已成功儲存！");
                } else {
                    showToast("儲存失敗：" + res.message);
                }
            } catch (e) {
                showToast("伺服器連線異常。");
            }
        });
    }

    // Save Weights
    const saveWeightsBtn = document.getElementById('saveWeightsBtn');
    if (saveWeightsBtn) {
        saveWeightsBtn.addEventListener('click', async () => {
            try {
                const resp = await fetch('/api/config-rules/save-weights', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        consecutive_weight: weightConsecutive.value,
                        no_teach_penalty: weightNoTeach.value,
                        no_sub_penalty: weightNoSub.value,
                        spreading_weight: weightSpreading.value
                    })
                });
                const res = await resp.json();
                if (res.status === 'success') {
                    showToast(res.message);
                } else {
                    showToast("儲存失敗：" + res.message);
                }
            } catch (e) {
                showToast("伺服器連線異常。");
            }
        });
    }
}

function renderRuleGrid(tbodyId) {
    const tbody = document.getElementById(tbodyId);
    if (!tbody) return;
    tbody.innerHTML = '';

    for (let p = 1; p <= 8; p++) {
        const tr = document.createElement('tr');
        const tdLabel = document.createElement('td');
        tdLabel.style.fontWeight = 'bold';
        tdLabel.style.background = 'rgba(255,255,255,0.03)';
        tdLabel.textContent = `第 ${p} 節`;
        tr.appendChild(tdLabel);

        for (let d = 1; d <= 5; d++) {
            const td = document.createElement('td');
            td.dataset.slot = `${d}-${p}`;
            td.style.cursor = 'pointer';
            td.style.userSelect = 'none';
            td.textContent = '可排';

            td.addEventListener('click', () => {
                if (td.classList.contains('slot-forbidden')) {
                    td.classList.remove('slot-forbidden');
                    td.style.background = '';
                    td.style.color = '';
                    td.textContent = '可排';
                } else {
                    td.classList.add('slot-forbidden');
                    td.style.background = 'rgba(239, 68, 68, 0.3)';
                    td.style.color = '#f87171';
                    td.textContent = '禁止';
                }
            });

            tr.appendChild(td);
        }
        tbody.appendChild(tr);
    }
}

function updateGridSlots(tbodyId, activeSlots) {
    const slotSet = new Set(activeSlots);
    const tbody = document.getElementById(tbodyId);
    if (!tbody) return;
    const cells = tbody.querySelectorAll('td[data-slot]');
    cells.forEach(cell => {
        const slot = cell.dataset.slot;
        if (slotSet.has(slot)) {
            cell.classList.add('slot-forbidden');
            cell.style.background = 'rgba(239, 68, 68, 0.3)';
            cell.style.color = '#f87171';
            cell.textContent = '禁止';
        } else {
            cell.classList.remove('slot-forbidden');
            cell.style.background = '';
            cell.style.color = '';
            cell.textContent = '可排';
        }
    });
}

function getGridActiveSlots(tbodyId) {
    const tbody = document.getElementById(tbodyId);
    if (!tbody) return [];
    const active = [];
    const cells = tbody.querySelectorAll('td.slot-forbidden');
    cells.forEach(cell => {
        if (cell.dataset.slot) {
            active.push(cell.dataset.slot);
        }
    });
    return active;
}

async function initSettingsModal() {
    const teacherSelectRule = document.getElementById('teacherSelectRule');
    const classSelectRule = document.getElementById('classSelectRule');
    const subSelectRule = document.getElementById('subSelectRule');

    if (metadata.teachers && teacherSelectRule && teacherSelectRule.options.length <= 1) {
        metadata.teachers.forEach(t => {
            const opt = document.createElement('option');
            opt.value = t.code;
            opt.textContent = `${t.name} (${t.code})`;
            teacherSelectRule.appendChild(opt);
        });
    }

    if (metadata.classes && classSelectRule && classSelectRule.options.length <= 1) {
        metadata.classes.forEach(c => {
            const opt = document.createElement('option');
            opt.value = c.code;
            opt.textContent = `${c.name} (${c.code})`;
            classSelectRule.appendChild(opt);
        });
    }

    if (subSelectRule && subSelectRule.options.length <= 1) {
        const defaultSubjects = [
            {code: "901", name: "體育"},
            {code: "101", name: "國文"},
            {code: "102", name: "英文"},
            {code: "103", name: "數學"},
            {code: "104", name: "物理"},
            {code: "105", name: "化學"},
            {code: "106", name: "生物"},
            {code: "107", name: "歷史"},
            {code: "108", name: "地理"},
            {code: "109", name: "公民"}
        ];
        defaultSubjects.forEach(s => {
            const opt = document.createElement('option');
            opt.value = s.code;
            opt.textContent = `${s.name} (${s.code})`;
            subSelectRule.appendChild(opt);
        });
    }

    try {
        const resp = await fetch('/api/config-rules');
        const data = await resp.json();
        if (data.status === 'success') {
            configRulesData = data;
            const w = data.weights || {};
            if (document.getElementById('weightConsecutive')) {
                document.getElementById('weightConsecutive').value = w.consecutive_weight || 500;
                document.getElementById('weightConsecutiveVal').textContent = w.consecutive_weight || 500;
                
                document.getElementById('weightNoTeach').value = w.no_teach_penalty || 200;
                document.getElementById('weightNoTeachVal').textContent = w.no_teach_penalty || 200;

                document.getElementById('weightNoSub').value = w.no_sub_penalty || 200;
                document.getElementById('weightNoSubVal').textContent = w.no_sub_penalty || 200;

                document.getElementById('weightSpreading').value = w.spreading_weight || 10;
                document.getElementById('weightSpreadingVal').textContent = w.spreading_weight || 10;
            }
        }
    } catch (e) {
        console.error("Init settings modal config rules fetch error:", e);
    }

    const assignClassSelect = document.getElementById('assignClassSelect');
    if (assignClassSelect && assignClassSelect.dataset.listener !== 'true') {
        assignClassSelect.dataset.listener = 'true';
        assignClassSelect.addEventListener('change', renderCourseAssignTable);
    }

    const assignTeacherSelect = document.getElementById('assignTeacherSelect');
    if (assignTeacherSelect && assignTeacherSelect.dataset.listener !== 'true') {
        assignTeacherSelect.dataset.listener = 'true';
        assignTeacherSelect.addEventListener('change', renderTeacherAssignTable);
    }

    const assignModeClassBtn = document.getElementById('assignModeClassBtn');
    const assignModeTeacherBtn = document.getElementById('assignModeTeacherBtn');
    const assignClassModeWrapper = document.getElementById('assignClassModeWrapper');
    const assignTeacherModeWrapper = document.getElementById('assignTeacherModeWrapper');

    if (assignModeClassBtn && assignModeTeacherBtn && assignModeClassBtn.dataset.listener !== 'true') {
        assignModeClassBtn.dataset.listener = 'true';
        assignModeClassBtn.addEventListener('click', () => {
            currentAssignMode = 'class';
            assignModeClassBtn.style.background = '#6366f1';
            assignModeTeacherBtn.style.background = 'transparent';
            assignClassModeWrapper.style.display = 'flex';
            assignTeacherModeWrapper.style.display = 'none';
            renderCourseAssignTable();
        });
        assignModeTeacherBtn.addEventListener('click', () => {
            currentAssignMode = 'teacher';
            assignModeTeacherBtn.style.background = '#6366f1';
            assignModeClassBtn.style.background = 'transparent';
            assignTeacherModeWrapper.style.display = 'flex';
            assignClassModeWrapper.style.display = 'none';
            renderTeacherAssignTable();
        });
    }
}

let currentAssignMode = 'class';
let allCourseAssignmentsData = [];
let allTeacherAssignmentsData = [];

async function loadCourseAssignments() {
    const assignClassSelect = document.getElementById('assignClassSelect');
    const assignTeacherSelect = document.getElementById('assignTeacherSelect');
    const assignAddClassSelect = document.getElementById('assignAddClassSelect');
    const assignAddSubSelect = document.getElementById('assignAddSubSelect');
    const addTeacherAssignBtn = document.getElementById('addTeacherAssignBtn');

    if (!assignClassSelect || !assignTeacherSelect) return;

    if (metadata.classes && assignClassSelect.options.length <= 1) {
        metadata.classes.forEach(c => {
            const opt = document.createElement('option');
            opt.value = c.code;
            opt.textContent = `${c.name} (${c.code})`;
            assignClassSelect.appendChild(opt);
        });
    }

    if (metadata.classes && assignAddClassSelect && assignAddClassSelect.options.length <= 1) {
        metadata.classes.forEach(c => {
            const opt = document.createElement('option');
            opt.value = c.code;
            opt.textContent = `${c.name} (${c.code})`;
            assignAddClassSelect.appendChild(opt);
        });
    }

    if (metadata.teachers && assignTeacherSelect.options.length <= 1) {
        metadata.teachers.forEach(t => {
            const opt = document.createElement('option');
            opt.value = t.code;
            opt.textContent = `${t.name} (${t.code})`;
            assignTeacherSelect.appendChild(opt);
        });
    }

    if (assignAddSubSelect && assignAddSubSelect.options.length <= 1) {
        const defaultSubjects = [
            {code: "101", name: "國文"},
            {code: "102", name: "英文"},
            {code: "103", name: "數學"},
            {code: "104", name: "物理"},
            {code: "105", name: "化學"},
            {code: "106", name: "生物"},
            {code: "107", name: "歷史"},
            {code: "108", name: "地理"},
            {code: "109", name: "公民"},
            {code: "901", name: "體育"},
            {code: "981", name: "彈性學習"}
        ];
        defaultSubjects.forEach(s => {
            const opt = document.createElement('option');
            opt.value = s.code;
            opt.textContent = `${s.name} (${s.code})`;
            assignAddSubSelect.appendChild(opt);
        });
    }

    if (addTeacherAssignBtn && addTeacherAssignBtn.dataset.listener !== 'true') {
        addTeacherAssignBtn.dataset.listener = 'true';
        addTeacherAssignBtn.addEventListener('click', async () => {
            const selectedTeacher = assignTeacherSelect.value;
            const selectedClass = assignAddClassSelect.value;
            const selectedSub = assignAddSubSelect.value;
            const assignAddHoursInput = document.getElementById('assignAddHoursInput');
            const hoursVal = assignAddHoursInput ? assignAddHoursInput.value : 4;

            if (!selectedTeacher) {
                showToast("請先選擇教師！");
                return;
            }
            if (!selectedClass || !selectedSub) {
                showToast("請選擇授課班級與科目！");
                return;
            }

            const tObj = metadata.teachers ? metadata.teachers.find(t => t.code === selectedTeacher) : null;
            const tName = tObj ? tObj.name : '';

            try {
                const resp = await fetch('/api/save-course-assignment', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        class_code: selectedClass,
                        subject_code: selectedSub,
                        teacher_code: selectedTeacher,
                        teacher_name: tName,
                        hours: hoursVal
                    })
                });
                const res = await resp.json();
                if (res.status === 'success') {
                    showToast(res.message);
                    await loadCourseAssignments();
                } else {
                    showToast("指派失敗：" + res.message);
                }
            } catch (e) {
                showToast("伺服器連線異常。");
            }
        });
    }

    try {
        const resp = await fetch('/api/course-assignments');
        const data = await resp.json();
        if (data.status === 'success') {
            allCourseAssignmentsData = data.assignments || [];
            allTeacherAssignmentsData = data.teacher_assignments || [];
            if (currentAssignMode === 'class') {
                renderCourseAssignTable();
            } else {
                renderTeacherAssignTable();
            }
        }
    } catch (e) {
        console.error("Load course assignments failed:", e);
    }
}

function renderCourseAssignTable() {
    const assignClassSelect = document.getElementById('assignClassSelect');
    const container = document.getElementById('assignTableContainer');
    const tbody = document.getElementById('assignTableBody');
    const thead = document.getElementById('assignTableHead');
    if (!assignClassSelect || !container || !tbody || !thead) return;

    thead.innerHTML = `
        <tr>
            <th>科目名稱 (代碼)</th>
            <th>每週節數</th>
            <th>目前授課教師</th>
            <th>變更配課教師</th>
            <th>操作</th>
        </tr>
    `;

    const selectedClass = assignClassSelect.value;
    if (!selectedClass) {
        container.style.display = 'none';
        return;
    }

    const classInfo = allCourseAssignmentsData.find(c => c.class_code === selectedClass);
    if (!classInfo || !classInfo.subjects || classInfo.subjects.length === 0) {
        tbody.innerHTML = '<tr><td colspan="5" style="text-align: center; color: var(--text-muted);">此班級暫無配課資料</td></tr>';
        container.style.display = 'block';
        return;
    }

    tbody.innerHTML = '';
    container.style.display = 'block';

    classInfo.subjects.forEach(sub => {
        const tr = document.createElement('tr');

        // Subject name & code
        const tdSub = document.createElement('td');
        tdSub.style.fontWeight = '500';
        tdSub.textContent = `${sub.subject_name} (${sub.subject_code})`;
        tr.appendChild(tdSub);

        // Editable Hours Input
        const tdHours = document.createElement('td');
        const hoursInput = document.createElement('input');
        hoursInput.type = 'number';
        hoursInput.min = '1';
        hoursInput.max = '10';
        hoursInput.value = sub.hours;
        hoursInput.style.width = '60px';
        hoursInput.style.padding = '4px 6px';
        hoursInput.style.borderRadius = '4px';
        hoursInput.style.background = 'rgba(15, 23, 42, 0.8)';
        hoursInput.style.color = '#38bdf8';
        hoursInput.style.fontWeight = 'bold';
        hoursInput.style.border = '1px solid var(--border-color)';
        tdHours.appendChild(hoursInput);
        tr.appendChild(tdHours);

        // Current Teacher
        const tdCurrT = document.createElement('td');
        tdCurrT.style.color = '#38bdf8';
        tdCurrT.textContent = sub.teacher_name ? `${sub.teacher_name} (${sub.teacher_code})` : '未指定';
        tr.appendChild(tdCurrT);

        // New Teacher Select
        const tdNewT = document.createElement('td');
        const sel = document.createElement('select');
        sel.style.padding = '4px 8px';
        sel.style.borderRadius = '4px';
        sel.style.background = 'rgba(15, 23, 42, 0.8)';
        sel.style.color = '#fff';
        sel.style.border = '1px solid var(--border-color)';

        const defaultOpt = document.createElement('option');
        defaultOpt.value = '';
        defaultOpt.textContent = '-- 選擇任課教師 --';
        sel.appendChild(defaultOpt);

        if (metadata.teachers) {
            metadata.teachers.forEach(t => {
                const opt = document.createElement('option');
                opt.value = t.code;
                opt.textContent = `${t.name} (${t.code})`;
                if (t.code === sub.teacher_code) {
                    opt.selected = true;
                }
                sel.appendChild(opt);
            });
        }
        tdNewT.appendChild(sel);
        tr.appendChild(tdNewT);

        // Action Save & Delete Buttons
        const tdAct = document.createElement('td');
        tdAct.style.display = 'flex';
        tdAct.style.gap = '6px';
        tdAct.style.justifyContent = 'center';

        const btn = document.createElement('button');
        btn.className = 'solver-action-btn primary-btn';
        btn.style.padding = '4px 10px';
        btn.style.fontSize = '0.8rem';
        btn.style.background = '#6366f1';
        btn.innerHTML = '<i class="fa-solid fa-floppy-disk"></i> 儲存';

        btn.addEventListener('click', async () => {
            const newTCode = sel.value || sub.teacher_code;
            const newHours = hoursInput.value;
            if (!newTCode) {
                showToast("請選擇配課教師！");
                return;
            }
            const teacherObj = metadata.teachers ? metadata.teachers.find(t => t.code === newTCode) : null;
            const newTName = teacherObj ? teacherObj.name : sub.teacher_name;

            try {
                const resp = await fetch('/api/save-course-assignment', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        class_code: selectedClass,
                        subject_code: sub.subject_code,
                        teacher_code: newTCode,
                        teacher_name: newTName,
                        hours: newHours
                    })
                });
                const res = await resp.json();
                if (res.status === 'success') {
                    showToast(res.message);
                    sub.teacher_code = newTCode;
                    sub.teacher_name = newTName;
                    sub.hours = parseInt(newHours);
                    tdCurrT.textContent = newTName ? `${newTName} (${newTCode})` : newTCode;
                    await loadCourseAssignments();
                } else {
                    showToast("儲存失敗：" + res.message);
                }
            } catch (e) {
                showToast("伺服器連線異常。");
            }
        });

        const delBtn = document.createElement('button');
        delBtn.className = 'solver-action-btn secondary-btn';
        delBtn.style.padding = '4px 10px';
        delBtn.style.fontSize = '0.8rem';
        delBtn.style.background = 'rgba(239, 68, 68, 0.2)';
        delBtn.style.borderColor = 'rgba(239, 68, 68, 0.4)';
        delBtn.style.color = '#ef4444';
        delBtn.innerHTML = '<i class="fa-solid fa-trash"></i> 刪除';

        delBtn.addEventListener('click', async () => {
            if (!confirm(`確定要移除 ${classInfo.class_name} 班的 ${sub.subject_name} 配課嗎？`)) return;
            try {
                const resp = await fetch('/api/delete-course-assignment', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        class_code: selectedClass,
                        subject_code: sub.subject_code
                    })
                });
                const res = await resp.json();
                if (res.status === 'success') {
                    showToast(res.message);
                    await loadCourseAssignments();
                } else {
                    showToast("刪除失敗：" + res.message);
                }
            } catch (e) {
                showToast("伺服器連線異常。");
            }
        });

        tdAct.appendChild(btn);
        tdAct.appendChild(delBtn);
        tr.appendChild(tdAct);

        tbody.appendChild(tr);
    });
}

function renderTeacherAssignTable() {
    const assignTeacherSelect = document.getElementById('assignTeacherSelect');
    const container = document.getElementById('assignTableContainer');
    const tbody = document.getElementById('assignTableBody');
    const thead = document.getElementById('assignTableHead');
    const badge = document.getElementById('teacherTotalHoursBadge');
    if (!assignTeacherSelect || !container || !tbody || !thead) return;

    const selectedTeacher = assignTeacherSelect.value;
    if (!selectedTeacher) {
        container.style.display = 'none';
        if (badge) badge.textContent = '總節數：0 節';
        return;
    }

    const tInfo = allTeacherAssignmentsData.find(t => t.teacher_code === selectedTeacher);
    if (!tInfo || !tInfo.courses || tInfo.courses.length === 0) {
        tbody.innerHTML = '<tr><td colspan="5" style="text-align: center; color: var(--text-muted);">此教師暫無配課課程。可利用上方選單直接指派配課！</td></tr>';
        container.style.display = 'block';
        if (badge) badge.textContent = '總節數：0 節';
        return;
    }

    if (badge) badge.textContent = `總授課節數：${tInfo.total_hours} 節`;

    thead.innerHTML = `
        <tr>
            <th>授課班級 (代碼)</th>
            <th>科目名稱 (代碼)</th>
            <th>每週授課節數</th>
            <th>配課狀態</th>
        </tr>
    `;

    tbody.innerHTML = '';
    container.style.display = 'block';

    tInfo.courses.forEach(c => {
        const tr = document.createElement('tr');

        // Class Name & Code
        const tdClass = document.createElement('td');
        tdClass.style.fontWeight = '500';
        tdClass.textContent = `${c.class_name} (${c.class_code})`;
        tr.appendChild(tdClass);

        // Subject Name & Code
        const tdSub = document.createElement('td');
        tdSub.textContent = `${c.subject_name} (${c.subject_code})`;
        tr.appendChild(tdSub);

        // Hours
        const tdHours = document.createElement('td');
        tdHours.style.color = '#38bdf8';
        tdHours.style.fontWeight = 'bold';
        tdHours.textContent = `${c.hours} 節`;
        tr.appendChild(tdHours);

        // Status
        const tdStatus = document.createElement('td');
        tdStatus.innerHTML = '<span style="color: #34d399;"><i class="fa-solid fa-circle-check"></i> 授課中</span>';
        tr.appendChild(tdStatus);

        tbody.appendChild(tr);
    });
}

let currentCatalogMode = 'master';
let masterSubjectCatalogData = [];
let gradeCurriculumData = {};

async function loadSubjectCatalog() {
    const catalogModeMasterBtn = document.getElementById('catalogModeMasterBtn');
    const catalogModeGradeBtn = document.getElementById('catalogModeGradeBtn');
    const catalogMasterWrapper = document.getElementById('catalogMasterWrapper');
    const catalogGradeWrapper = document.getElementById('catalogGradeWrapper');
    const curriculumGradeSelect = document.getElementById('curriculumGradeSelect');
    const saveNewMasterSubBtn = document.getElementById('saveNewMasterSubBtn');
    const addGradeCurriculumBtn = document.getElementById('addGradeCurriculumBtn');

    if (catalogModeMasterBtn && catalogModeMasterBtn.dataset.listener !== 'true') {
        catalogModeMasterBtn.dataset.listener = 'true';
        catalogModeMasterBtn.addEventListener('click', () => {
            currentCatalogMode = 'master';
            catalogModeMasterBtn.style.background = '#6366f1';
            catalogModeGradeBtn.style.background = 'transparent';
            catalogMasterWrapper.style.display = 'block';
            catalogGradeWrapper.style.display = 'none';
            renderMasterSubjectTable();
        });
        catalogModeGradeBtn.addEventListener('click', () => {
            currentCatalogMode = 'grade';
            catalogModeGradeBtn.style.background = '#6366f1';
            catalogModeMasterBtn.style.background = 'transparent';
            catalogGradeWrapper.style.display = 'block';
            catalogMasterWrapper.style.display = 'none';
            renderGradeCurriculumTable();
        });
    }

    if (curriculumGradeSelect && curriculumGradeSelect.dataset.listener !== 'true') {
        curriculumGradeSelect.dataset.listener = 'true';
        curriculumGradeSelect.addEventListener('change', renderGradeCurriculumTable);
    }

    if (saveNewMasterSubBtn && saveNewMasterSubBtn.dataset.listener !== 'true') {
        saveNewMasterSubBtn.dataset.listener = 'true';
        saveNewMasterSubBtn.addEventListener('click', async () => {
            const code = document.getElementById('catNewCodeInput').value.trim();
            const name = document.getElementById('catNewNameInput').value.trim();
            const category = document.getElementById('catNewCategoryInput').value.trim() || '一般';
            const hours = document.getElementById('catNewHoursInput').value || 2;

            if (!code || !name) {
                showToast("請輸入學科代碼與學科名稱！");
                return;
            }

            try {
                const resp = await fetch('/api/save-subject-catalog', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ code, name, category, default_hours: hours })
                });
                const res = await resp.json();
                if (res.status === 'success') {
                    showToast(res.message);
                    document.getElementById('catNewCodeInput').value = '';
                    document.getElementById('catNewNameInput').value = '';
                    document.getElementById('catNewCategoryInput').value = '';
                    await loadSubjectCatalog();
                } else {
                    showToast("新增失敗：" + res.message);
                }
            } catch (e) {
                showToast("伺服器連線異常。");
            }
        });
    }

    if (addGradeCurriculumBtn && addGradeCurriculumBtn.dataset.listener !== 'true') {
        addGradeCurriculumBtn.dataset.listener = 'true';
        addGradeCurriculumBtn.addEventListener('click', async () => {
            const grade = document.getElementById('curriculumGradeSelect').value;
            const subCode = document.getElementById('curriculumSubSelect').value;
            const hours = document.getElementById('curriculumHoursInput').value || 4;

            if (!subCode) {
                showToast("請選擇要指派給該年級的學科！");
                return;
            }

            const subObj = masterSubjectCatalogData.find(s => s.code === subCode);
            const subName = subObj ? subObj.name : subCode;

            try {
                const resp = await fetch('/api/save-grade-curriculum', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ grade, subject_code: subCode, subject_name: subName, hours })
                });
                const res = await resp.json();
                if (res.status === 'success') {
                    showToast(res.message);
                    await loadSubjectCatalog();
                } else {
                    showToast("指派失敗：" + res.message);
                }
            } catch (e) {
                showToast("伺服器連線異常。");
            }
        });
    }

    try {
        const resp = await fetch('/api/subject-catalog');
        const data = await resp.json();
        if (data.status === 'success') {
            masterSubjectCatalogData = data.subject_catalog || [];
            gradeCurriculumData = data.grade_curriculum || {};

            // Populate curriculumSubSelect dropdown
            const curriculumSubSelect = document.getElementById('curriculumSubSelect');
            if (curriculumSubSelect) {
                curriculumSubSelect.innerHTML = '<option value="">-- 選擇學科 --</option>';
                masterSubjectCatalogData.forEach(s => {
                    const opt = document.createElement('option');
                    opt.value = s.code;
                    opt.textContent = `${s.name} (${s.code})`;
                    curriculumSubSelect.appendChild(opt);
                });
            }

            if (currentCatalogMode === 'master') {
                renderMasterSubjectTable();
            } else {
                renderGradeCurriculumTable();
            }
        }
    } catch (e) {
        console.error("Load subject catalog failed:", e);
    }
}

function renderMasterSubjectTable() {
    const tbody = document.getElementById('masterSubjectTableBody');
    if (!tbody) return;

    tbody.innerHTML = '';
    masterSubjectCatalogData.forEach(s => {
        const tr = document.createElement('tr');

        const tdCode = document.createElement('td');
        tdCode.style.fontWeight = 'bold';
        tdCode.style.color = '#818cf8';
        tdCode.textContent = s.code;
        tr.appendChild(tdCode);

        const tdName = document.createElement('td');
        tdName.style.fontWeight = '500';
        tdName.textContent = s.name;
        tr.appendChild(tdName);

        const tdCat = document.createElement('td');
        tdCat.textContent = s.category || '一般領域';
        tr.appendChild(tdCat);

        const tdHours = document.createElement('td');
        tdHours.style.color = '#38bdf8';
        tdHours.style.fontWeight = 'bold';
        tdHours.textContent = `${s.default_hours || 4} 節`;
        tr.appendChild(tdHours);

        const tdAct = document.createElement('td');
        const delBtn = document.createElement('button');
        delBtn.className = 'solver-action-btn secondary-btn';
        delBtn.style.padding = '4px 10px';
        delBtn.style.fontSize = '0.8rem';
        delBtn.style.background = 'rgba(239, 68, 68, 0.2)';
        delBtn.style.borderColor = 'rgba(239, 68, 68, 0.4)';
        delBtn.style.color = '#ef4444';
        delBtn.innerHTML = '<i class="fa-solid fa-trash"></i> 刪除';

        delBtn.addEventListener('click', async () => {
            if (!confirm(`確定要刪除學科代碼 ${s.code} (${s.name}) 嗎？`)) return;
            try {
                const resp = await fetch('/api/save-subject-catalog', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ code: s.code, delete: true })
                });
                const res = await resp.json();
                if (res.status === 'success') {
                    showToast(res.message);
                    await loadSubjectCatalog();
                } else {
                    showToast("刪除失敗：" + res.message);
                }
            } catch (e) {
                showToast("伺服器連線異常。");
            }
        });

        tdAct.appendChild(delBtn);
        tr.appendChild(tdAct);

        tbody.appendChild(tr);
    });
}

function renderGradeCurriculumTable() {
    const gradeSelect = document.getElementById('curriculumGradeSelect');
    const tbody = document.getElementById('gradeCurriculumTableBody');
    if (!gradeSelect || !tbody) return;

    const selectedGrade = gradeSelect.value;
    const items = gradeCurriculumData[selectedGrade] || [];

    tbody.innerHTML = '';
    if (items.length === 0) {
        tbody.innerHTML = '<tr><td colspan="4" style="text-align: center; color: var(--text-muted);">該年級尚未設定應修課程，可利用上方選單進行指派！</td></tr>';
        return;
    }

    items.forEach(c => {
        const tr = document.createElement('tr');

        const tdCode = document.createElement('td');
        tdCode.style.fontWeight = 'bold';
        tdCode.style.color = '#818cf8';
        tdCode.textContent = c.subject_code;
        tr.appendChild(tdCode);

        const tdName = document.createElement('td');
        tdName.style.fontWeight = '500';
        tdName.textContent = c.subject_name;
        tr.appendChild(tdName);

        const tdHours = document.createElement('td');
        tdHours.style.color = '#38bdf8';
        tdHours.style.fontWeight = 'bold';
        tdHours.textContent = `${c.hours} 節`;
        tr.appendChild(tdHours);

        const tdAct = document.createElement('td');
        const delBtn = document.createElement('button');
        delBtn.className = 'solver-action-btn secondary-btn';
        delBtn.style.padding = '4px 10px';
        delBtn.style.fontSize = '0.8rem';
        delBtn.style.background = 'rgba(239, 68, 68, 0.2)';
        delBtn.style.borderColor = 'rgba(239, 68, 68, 0.4)';
        delBtn.style.color = '#ef4444';
        delBtn.innerHTML = '<i class="fa-solid fa-trash"></i> 移除';

        delBtn.addEventListener('click', async () => {
            if (!confirm(`確定要為年級 ${selectedGrade} 移除 ${c.subject_name} 課程嗎？`)) return;
            try {
                const resp = await fetch('/api/save-grade-curriculum', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ grade: selectedGrade, subject_code: c.subject_code, delete: true })
                });
                const res = await resp.json();
                if (res.status === 'success') {
                    showToast(res.message);
                    await loadSubjectCatalog();
                } else {
                    showToast("移除失敗：" + res.message);
                }
            } catch (e) {
                showToast("伺服器連線異常。");
            }
        });

        tdAct.appendChild(delBtn);
        tr.appendChild(tdAct);

        tbody.appendChild(tr);
    });
}

let restorePointsData = [];

async function loadRestorePoints() {
    const importInput = document.getElementById('importConfigFileInput');
    if (importInput && importInput.dataset.listener !== 'true') {
        importInput.dataset.listener = 'true';
        importInput.addEventListener('change', async (e) => {
            const file = e.target.files[0];
            if (!file) return;

            const formData = new FormData();
            formData.append('file', file);

            try {
                const resp = await fetch('/api/import-config', {
                    method: 'POST',
                    body: formData
                });
                const res = await resp.json();
                if (res.status === 'success') {
                    showToast(res.message);
                    setTimeout(() => {
                        window.location.reload();
                    }, 1200);
                } else {
                    showToast("匯入失敗：" + res.message);
                }
            } catch (err) {
                showToast("伺服器連線異常。");
            }
            importInput.value = '';
        });
    }

    const createBtn = document.getElementById('createNewRestorePointBtn');
    if (createBtn && createBtn.dataset.listener !== 'true') {
        createBtn.dataset.listener = 'true';
        createBtn.addEventListener('click', async () => {
            const noteInput = document.getElementById('restoreNoteInput');
            const note = noteInput ? noteInput.value.trim() : '';

            try {
                const resp = await fetch('/api/create-restore-point', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ note })
                });
                const res = await resp.json();
                if (res.status === 'success') {
                    showToast(res.message);
                    if (noteInput) noteInput.value = '';
                    await loadRestorePoints();
                } else {
                    showToast("建立失敗：" + res.message);
                }
            } catch (e) {
                showToast("伺服器連線異常。");
            }
        });
    }

    try {
        const resp = await fetch('/api/restore-points');
        const data = await resp.json();
        if (data.status === 'success') {
            restorePointsData = data.restore_points || [];
            renderRestorePointsTable();
        }
    } catch (e) {
        console.error("Load restore points failed:", e);
    }
}

function renderRestorePointsTable() {
    const tbody = document.getElementById('restorePointsTableBody');
    if (!tbody) return;

    tbody.innerHTML = '';
    if (restorePointsData.length === 0) {
        tbody.innerHTML = '<tr><td colspan="5" style="text-align: center; color: var(--text-muted);">尚未建立歷史還原點。點擊上方「拍攝全校設定與課表快照」按鈕即可隨時備份當前狀態！</td></tr>';
        return;
    }

    restorePointsData.forEach(p => {
        const tr = document.createElement('tr');

        // ID
        const tdId = document.createElement('td');
        tdId.style.fontWeight = 'bold';
        tdId.style.color = '#818cf8';
        tdId.textContent = p.id;
        tr.appendChild(tdId);

        // Timestamp
        const tdTime = document.createElement('td');
        tdTime.textContent = p.timestamp;
        tr.appendChild(tdTime);

        // Note
        const tdNote = document.createElement('td');
        tdNote.style.fontWeight = '500';
        tdNote.textContent = p.note || '系統自動備份快照';
        tr.appendChild(tdNote);

        // Content Backup Badge
        const tdContent = document.createElement('td');
        if (p.has_excel) {
            tdContent.innerHTML = '<span style="color: #34d399; font-size: 0.8rem;"><i class="fa-solid fa-file-excel"></i> 全校規則 + 課表 Excel</span>';
        } else {
            tdContent.innerHTML = '<span style="color: #38bdf8; font-size: 0.8rem;"><i class="fa-solid fa-gear"></i> 全校規則與配課設定</span>';
        }
        tr.appendChild(tdContent);

        // Action Buttons
        const tdAct = document.createElement('td');
        tdAct.style.display = 'flex';
        tdAct.style.gap = '6px';
        tdAct.style.justifyContent = 'center';

        // Restore Button
        const restoreBtn = document.createElement('button');
        restoreBtn.className = 'solver-action-btn primary-btn';
        restoreBtn.style.padding = '4px 10px';
        restoreBtn.style.fontSize = '0.8rem';
        restoreBtn.style.background = '#6366f1';
        restoreBtn.innerHTML = '<i class="fa-solid fa-rotate-left"></i> 立即還原';

        restoreBtn.addEventListener('click', async () => {
            if (!confirm(`⚠️ 警告：確定要將全校系統設定與課表還原至【${p.note} (${p.timestamp})】嗎？\n現有的未備份變更將會被覆蓋！`)) return;

            try {
                const resp = await fetch('/api/restore-checkpoint', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ id: p.id })
                });
                const res = await resp.json();
                if (res.status === 'success') {
                    showToast(res.message);
                    setTimeout(() => {
                        window.location.reload();
                    }, 1200);
                } else {
                    showToast("還原失敗：" + res.message);
                }
            } catch (e) {
                showToast("伺服器連線異常。");
            }
        });

        // Delete Button
        const delBtn = document.createElement('button');
        delBtn.className = 'solver-action-btn secondary-btn';
        delBtn.style.padding = '4px 10px';
        delBtn.style.fontSize = '0.8rem';
        delBtn.style.background = 'rgba(239, 68, 68, 0.2)';
        delBtn.style.borderColor = 'rgba(239, 68, 68, 0.4)';
        delBtn.style.color = '#ef4444';
        delBtn.innerHTML = '<i class="fa-solid fa-trash"></i> 刪除';

        delBtn.addEventListener('click', async () => {
            if (!confirm(`確定要刪除還原點快照 ${p.id} 嗎？`)) return;

            try {
                const resp = await fetch('/api/delete-restore-point', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ id: p.id })
                });
                const res = await resp.json();
                if (res.status === 'success') {
                    showToast(res.message);
                    await loadRestorePoints();
                } else {
                    showToast("刪除失敗：" + res.message);
                }
            } catch (e) {
                showToast("伺服器連線異常。");
            }
        });

        tdAct.appendChild(restoreBtn);
        tdAct.appendChild(delBtn);
        tr.appendChild(tdAct);

        tbody.appendChild(tr);
    });
}

