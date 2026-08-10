// Global state
let metadata = {
    classes: [],
    teachers: [],
    classrooms: [],
    period_times: {}
};

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
    setupSolverPanel();
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

    // Run solver
    runSolverBtn.addEventListener('click', async () => {
        // Disable buttons
        runSolverBtn.disabled = true;
        validateSolverBtn.disabled = true;
        
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
            solverConsole.scrollTop = solverConsole.scrollHeight;
        }
    });

    // Validate solver
    validateSolverBtn.addEventListener('click', async () => {
        runSolverBtn.disabled = true;
        validateSolverBtn.disabled = true;

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
            solverConsole.scrollTop = solverConsole.scrollHeight;
        }
    });
}
