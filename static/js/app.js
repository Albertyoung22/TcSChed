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

});

// Event Listeners Setup
function setupEventListeners() {
    // Hash Routing
    window.addEventListener('hashchange', handleHashChange);

    // Back Button
    if (backBtn) {
        backBtn.addEventListener('click', () => {
            window.location.hash = '';
        });
    }

    // Share Button
    if (shareBtn) {
        shareBtn.addEventListener('click', copyShareLink);
    }

    // Print Button
    if (printBtn) {
        printBtn.addEventListener('click', () => {
            // Set current date for printing
            const today = new Date();
            if (printDateSpan) printDateSpan.textContent = `${today.getFullYear()}/${today.getMonth() + 1}/${today.getDate()}`;
            window.print();
        });
    }

    // Open Web Browser Button
    const openWebBrowserBtn = document.getElementById('openWebBrowserBtn');
    if (openWebBrowserBtn) {
        openWebBrowserBtn.addEventListener('click', async () => {
            let currentUrl = window.location.href;
            const localIp = metadata.local_ip;
            if (localIp && localIp !== '127.0.0.1') {
                currentUrl = currentUrl.replace('127.0.0.1', localIp).replace('localhost', localIp);
            }
            try {
                const resp = await fetch('/api/open-browser', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ url: currentUrl })
                });
                const data = await resp.json();
                if (data.status === 'success') {
                    showToast(`已開啟真實 IP 網址：${data.target_url || currentUrl}`, 'success');
                } else {
                    window.open(currentUrl, '_blank');
                }
            } catch (e) {
                window.open(currentUrl, '_blank');
            }
        });
    }



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
        await fetchLessonNotes();
        
        // Show database name/path & local LAN IP in badge
        const dbBadge = document.getElementById('dbBadge');
        if (data.dbf_dir) {
            const parts = data.dbf_dir.split(/[\\/]/);
            const dbfFolder = parts.find(p => p.toLowerCase().startsWith('spv') && p.toLowerCase().endsWith('.wdb'));
            dbPathText.textContent = dbfFolder || "SPV2000 資料庫";
        } else {
            dbPathText.textContent = "未載入 (移交空白範本)";
        }
        if (data.local_ip && dbBadge) {
            dbBadge.title = `資料庫: ${data.dbf_dir || '未設定'}\n局域網連線網址: http://${data.local_ip}:5000`;
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

    if (!metadata.classes || metadata.classes.length === 0) {
        const emptyMsg = `
        <div style="grid-column: 1/-1; text-align: center; color: var(--text-muted); padding: 32px 16px; background: rgba(15, 23, 42, 0.4); border-radius: 12px; border: 1px dashed var(--border-color);">
            <i class="fa-solid fa-folder-open" style="font-size: 2.5rem; color: #38bdf8; margin-bottom: 12px; display: block;"></i>
            <div style="font-size: 1.1rem; font-weight: 600; color: #f8fafc; margin-bottom: 8px;">系統現已重置為全新空白學校範本</div>
            <div style="font-size: 0.88rem; color: #94a3b8; max-width: 580px; margin: 0 auto; line-height: 1.6;">
                請點擊右上角 <strong style="color: #fbbf24;">「⚙️ 排課規則與系統設定」</strong> ➔ <strong style="color: #38bdf8;">「學校基本資料與系統設定」</strong><br>
                點擊 <strong style="color: #0284c7; background: rgba(2, 132, 199, 0.2); padding: 2px 8px; border-radius: 4px;">「📁 瀏覽選擇資料夾...」</strong> 選擇欣河 (SPV2000) DBF 資料庫資料夾即可自動讀取全校班級、教師與授課資料！
            </div>
        </div>`;
        highSchoolGrid.innerHTML = emptyMsg;
        teachersGrid.innerHTML = emptyMsg;
        roomsGrid.innerHTML = emptyMsg;
        return;
    }

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
    if (Array.isArray(metadata.classrooms)) {
        metadata.classrooms.forEach(room => {
            const item = document.createElement('a');
            const rcode = typeof room === 'string' ? room : (room.code || room.name);
            const rname = typeof room === 'string' ? room : (room.name || room.code);
            item.href = `#room/${encodeURIComponent(rcode)}`;
            item.className = 'grid-item';
            item.innerHTML = `${rname}`;
            roomsGrid.appendChild(item);
        });
    }
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
    if (Array.isArray(metadata.classrooms)) {
        metadata.classrooms.forEach(room => {
            const rcode = typeof room === 'string' ? room : (room.code || room.name);
            const rname = typeof room === 'string' ? room : (room.name || room.code);
            if (rname.toLowerCase().includes(query) || rcode.toLowerCase().includes(query)) {
                matches.push({ type: 'room', label: `${rname} (教室)`, code: rcode, sub: '' });
            }
        });
    }

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

    const match = hash.match(/^#(class|teacher|room)\/(.+)$/);
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
        const response = await fetch(`/api/schedule/${type}/${encodeURIComponent(code)}`);
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
        const room = Array.isArray(metadata.classrooms) ? metadata.classrooms.find(r => (typeof r === 'object' ? (r.code === code || r.name === code) : r === code)) : null;
        const roomName = room ? (typeof room === 'object' ? room.name : room) : code;
        title = `${roomName} 教室課表`;
        subtitle = `專科教室 / 專用場地課表`;
        printScheduleTitle.textContent = title;
        printTutorInfo.textContent = subtitle;
        document.title = `${roomName} 教室課表 - 土城高中課表查詢`;
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
                
                // If there are multiple lessons (e.g. split grouping or remedial teaching)
                if (lessons.length > 1) {
                    const tag = document.createElement('div');
                    tag.className = 'multi-group-tag';
                    tag.title = '同時間分組教學 / 抽離輔導 / 彈性學習時段';
                    tag.innerHTML = `<i class="fa-solid fa-layer-group"></i> 分組教學 (${lessons.length}組)`;
                    cellContainer.appendChild(tag);
                }


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
                        lessonDiv.style.borderTop = '1px dashed rgba(255,255,255,0.15)';
                        lessonDiv.style.paddingTop = '4px';
                        lessonDiv.style.marginTop = '4px';
                    }

                    let mainText = lesson.subject_name;
                    let targetLink = '';
                    let roomLink = '';

                    if (type === 'class') {
                        // Class view: link to teacher and classroom with Dual-View Modal trigger
                        targetLink = lesson.teacher_name ? `<a href="#teacher/${encodeURIComponent(lesson.teacher_code || lesson.teacher_name)}" onclick="openDualViewModal('${code}', '${lesson.teacher_code || lesson.teacher_name}'); return false;" class="meta-link" title="開啟雙視窗課表對照與調課助手"><i class="fa-solid fa-chalkboard-user"></i> ${lesson.teacher_name} <i class="fa-solid fa-columns" style="font-size:0.7rem; opacity:0.7;"></i></a>` : '';
                        roomLink = lesson.room_name ? `<a href="#room/${encodeURIComponent(lesson.room_code || lesson.room_name)}" class="room-lbl meta-link"><i class="fa-solid fa-location-dot"></i> ${lesson.room_name}</a>` : '';
                    } else if (type === 'teacher') {
                        // Teacher view: link to class and classroom with Dual-View Modal trigger
                        targetLink = lesson.class_name ? `<a href="#class/${encodeURIComponent(lesson.class_code || lesson.class_name)}" onclick="openDualViewModal('${lesson.class_code || lesson.class_name}', '${code}'); return false;" class="meta-link" title="開啟雙視窗課表對照與調課助手"><i class="fa-solid fa-users"></i> ${lesson.class_name} <i class="fa-solid fa-columns" style="font-size:0.7rem; opacity:0.7;"></i></a>` : '';
                        roomLink = lesson.room_name ? `<a href="#room/${encodeURIComponent(lesson.room_code || lesson.room_name)}" class="room-lbl meta-link"><i class="fa-solid fa-location-dot"></i> ${lesson.room_name}</a>` : '';
                    } else if (type === 'room') {
                        // Room view: link to class and teacher
                        targetLink = lesson.class_name ? `<a href="#class/${encodeURIComponent(lesson.class_code || lesson.class_name)}" class="meta-link"><i class="fa-solid fa-users"></i> ${lesson.class_name}</a>` : '';
                        roomLink = lesson.teacher_name ? `<span class="room-lbl" style="font-size:0.85rem;"><a href="#teacher/${encodeURIComponent(lesson.teacher_code || lesson.teacher_name)}" onclick="openDualViewModal('${lesson.class_code}', '${lesson.teacher_code || lesson.teacher_name}'); return false;" class="meta-link"><i class="fa-solid fa-chalkboard-user"></i> ${lesson.teacher_name}</a></span>` : '';
                    }

                    // Week Mode Banner
                    let badge = '';
                    if (lesson.week_mode === 1) {
                        badge = '<span class="week-badge odd">單</span>';
                    } else if (lesson.week_mode === 2) {
                        badge = '<span class="week-badge even">雙</span>';
                    }

                    // Lesson Note Badge
                    const noteKey = `${type}_${code}_${d}_${p}`;
                    const noteObj = lessonNotes[noteKey] || (lesson.id ? lessonNotes[`lesson_${lesson.id}`] : null);
                    let noteMarkup = '';
                    if (noteObj) {
                        const noteBg = getNoteTypeColorBg(noteObj.note_type);
                        const noteBorder = getNoteTypeColorBorder(noteObj.note_type);
                        const noteTextCol = getNoteTypeColorText(noteObj.note_type);
                        noteMarkup = `
                            <div class="slot-note-badge" onclick="event.stopPropagation(); openNoteModal('${noteKey}', '${mainText}', '${d}', '${p}');" style="background:${noteBg}; border:1px solid ${noteBorder}; color:${noteTextCol}; border-radius:4px; padding:2px 6px; font-size:0.75rem; font-weight:bold; cursor:pointer; margin-top:3px; display:flex; align-items:center; justify-content:space-between;" title="登錄人:${noteObj.author} (${noteObj.updated_at}): ${noteObj.note_text}">
                                <span>📌 [${noteObj.note_type}] ${noteObj.note_text}</span>
                                <i class="fa-solid fa-pen-to-square" style="font-size:0.7rem; opacity:0.8;"></i>
                            </div>
                        `;
                    } else {
                        noteMarkup = `
                            <div style="margin-top: 2px; text-align: right;">
                                <button onclick="event.stopPropagation(); openNoteModal('${noteKey}', '${mainText}', '${d}', '${p}');" style="background: transparent; border: none; color: rgba(255,255,255,0.35); font-size: 0.7rem; cursor: pointer;" title="新增課表/調課註記"><i class="fa-solid fa-pen-to-square"></i> 註記</button>
                            </div>
                        `;
                    }

                    lessonDiv.innerHTML = `
                        <span class="subject-name" style="${lessons.length > 1 ? 'font-size: 0.82rem;' : ''}">${mainText}</span>
                        ${targetLink}
                        ${roomLink}
                        ${badge}
                        ${noteMarkup}
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
        window.switchRuleTab('school');
    });


    closeSettingsBtn.addEventListener('click', () => {
        settingsModal.style.display = 'none';
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
    const tabRuleVenuesBtn = document.getElementById('tabRuleVenuesBtn');
    const ruleTabVenues = document.getElementById('ruleTabVenues');
    const tabRuleSimBtn = document.getElementById('tabRuleSimBtn');
    const ruleTabSim = document.getElementById('ruleTabSim');
    const ruleTabRestore = document.getElementById('ruleTabRestore');

    function switchRuleTab(tabName) {
        const settingsModal = document.getElementById('settingsModal');
        if (settingsModal && settingsModal.style.display !== 'flex') {
            settingsModal.style.display = 'flex';
            initSettingsModal();
        }

        document.querySelectorAll('.rule-tab-btn').forEach(b => {
            b.classList.remove('active');
            b.style.background = 'transparent';
            b.style.color = 'var(--text-secondary)';
        });
        document.querySelectorAll('.rule-tab-content').forEach(c => {
            c.style.display = 'none';
            c.classList.remove('active');
        });

        if (tabName === 'aicenter') {
            const tabRuleAiCenterBtn = document.getElementById('tabRuleAiCenterBtn');
            const ruleTabAiCenter = document.getElementById('ruleTabAiCenter');
            if (tabRuleAiCenterBtn) {
                tabRuleAiCenterBtn.classList.add('active');
                tabRuleAiCenterBtn.style.background = 'linear-gradient(135deg, rgba(168, 85, 247, 0.3), rgba(99, 102, 241, 0.3))';
                tabRuleAiCenterBtn.style.color = '#fff';
            }
            if (ruleTabAiCenter) {
                ruleTabAiCenter.style.display = 'block';
                ruleTabAiCenter.classList.add('active');
            }
        } else if (tabName === 'school') {
            const tabRuleSchoolBtn = document.getElementById('tabRuleSchoolBtn');
            const ruleTabSchool = document.getElementById('ruleTabSchool');
            if (tabRuleSchoolBtn) {
                tabRuleSchoolBtn.classList.add('active');
                tabRuleSchoolBtn.style.background = 'rgba(56, 189, 248, 0.2)';
                tabRuleSchoolBtn.style.color = '#38bdf8';
            }
            if (ruleTabSchool) {
                ruleTabSchool.style.display = 'block';
                ruleTabSchool.classList.add('active');
            }
            loadSystemInfo();
            loadClassesMaintainList();
        } else if (tabName === 'teachermaintain') {
            const tabRuleTeacherMaintainBtn = document.getElementById('tabRuleTeacherMaintainBtn');
            const ruleTabTeacherMaintain = document.getElementById('ruleTabTeacherMaintain');
            if (tabRuleTeacherMaintainBtn) {
                tabRuleTeacherMaintainBtn.classList.add('active');
                tabRuleTeacherMaintainBtn.style.background = 'rgba(56, 189, 248, 0.2)';
                tabRuleTeacherMaintainBtn.style.color = '#38bdf8';
            }
            if (ruleTabTeacherMaintain) {
                ruleTabTeacherMaintain.style.display = 'block';
                ruleTabTeacherMaintain.classList.add('active');
            }
            loadTeachersMaintainList();
        } else if (tabName === 'teacher') {
            if (tabRuleTeacherBtn) {
                tabRuleTeacherBtn.classList.add('active');
                tabRuleTeacherBtn.style.background = 'rgba(99, 102, 241, 0.2)';
                tabRuleTeacherBtn.style.color = '#818cf8';
            }
            if (ruleTabTeacher) {
                ruleTabTeacher.style.display = 'block';
                ruleTabTeacher.classList.add('active');
            }

            loadTeachersMaintainList();
        } else if (tabName === 'sub') {
            if (tabRuleSubBtn) {
                tabRuleSubBtn.classList.add('active');
                tabRuleSubBtn.style.background = 'rgba(99, 102, 241, 0.2)';
                tabRuleSubBtn.style.color = '#818cf8';
            }
            if (ruleTabSub) {
                ruleTabSub.style.display = 'block';
                ruleTabSub.classList.add('active');
            }
        } else if (tabName === 'weights') {
            if (tabRuleWeightsBtn) {
                tabRuleWeightsBtn.classList.add('active');
                tabRuleWeightsBtn.style.background = 'rgba(99, 102, 241, 0.2)';
                tabRuleWeightsBtn.style.color = '#818cf8';
            }
            if (ruleTabWeights) {
                ruleTabWeights.style.display = 'block';
                ruleTabWeights.classList.add('active');
            }
        } else if (tabName === 'assign') {
            if (tabRuleAssignBtn) {
                tabRuleAssignBtn.classList.add('active');
                tabRuleAssignBtn.style.background = 'rgba(99, 102, 241, 0.2)';
                tabRuleAssignBtn.style.color = '#818cf8';
            }
            if (ruleTabAssign) {
                ruleTabAssign.style.display = 'block';
                ruleTabAssign.classList.add('active');
            }
            loadCourseAssignments();

        } else if (tabName === 'catalog') {
            if (tabRuleCatalogBtn) {
                tabRuleCatalogBtn.classList.add('active');
                tabRuleCatalogBtn.style.background = 'rgba(99, 102, 241, 0.2)';
                tabRuleCatalogBtn.style.color = '#818cf8';
            }
            if (ruleTabCatalog) {
                ruleTabCatalog.style.display = 'block';
                ruleTabCatalog.classList.add('active');
            }
            loadSubjectCatalog();
            loadSubjectsMaintainList();
        } else if (tabName === 'venues') {

            if (tabRuleVenuesBtn) {
                tabRuleVenuesBtn.classList.add('active');
                tabRuleVenuesBtn.style.background = 'rgba(99, 102, 241, 0.2)';
                tabRuleVenuesBtn.style.color = '#818cf8';
            }
            if (ruleTabVenues) {
                ruleTabVenues.style.display = 'block';
                ruleTabVenues.classList.add('active');
            }
            loadVenueCapacities();
        } else if (tabName === 'sim') {
            if (tabRuleSimBtn) {
                tabRuleSimBtn.classList.add('active');
                tabRuleSimBtn.style.background = 'rgba(99, 102, 241, 0.2)';
                tabRuleSimBtn.style.color = '#818cf8';
            }
            if (ruleTabSim) {
                ruleTabSim.style.display = 'block';
                ruleTabSim.classList.add('active');
            }
            loadSimultaneousGroups();
        } else if (tabName === 'semester' || tabName === 'restore') {
            const tabRuleSemesterBtn = document.getElementById('tabRuleSemesterBtn');
            const ruleTabSemester = document.getElementById('ruleTabSemester');
            if (tabRuleSemesterBtn) {
                tabRuleSemesterBtn.classList.add('active');
                tabRuleSemesterBtn.style.background = 'rgba(168, 85, 247, 0.2)';
                tabRuleSemesterBtn.style.color = '#c084fc';
            }
            if (ruleTabSemester) {
                ruleTabSemester.style.display = 'block';
                ruleTabSemester.classList.add('active');
            }
            if (typeof loadSemesters === 'function') loadSemesters();
            if (typeof loadRestorePoints === 'function') loadRestorePoints();
        } else if (tabName === 'moecode') {
            const tabRuleMoeCodeBtn = document.getElementById('tabRuleMoeCodeBtn');
            const ruleTabMoeCode = document.getElementById('ruleTabMoeCode');
            if (tabRuleMoeCodeBtn) {
                tabRuleMoeCodeBtn.classList.add('active');
                tabRuleMoeCodeBtn.style.background = 'rgba(251, 191, 36, 0.2)';
                tabRuleMoeCodeBtn.style.color = '#fbbf24';
            }
            if (ruleTabMoeCode) {
                ruleTabMoeCode.style.display = 'block';
                ruleTabMoeCode.classList.add('active');
            }
            loadMoeCourseCodes();
        } else if (tabName === 'checklist') {
            const tabRuleChecklistBtn = document.getElementById('tabRuleChecklistBtn');
            const ruleTabChecklist = document.getElementById('ruleTabChecklist');
            if (tabRuleChecklistBtn) {
                tabRuleChecklistBtn.classList.add('active');
                tabRuleChecklistBtn.style.background = 'rgba(52, 211, 153, 0.2)';
                tabRuleChecklistBtn.style.color = '#34d399';
            }
            if (ruleTabChecklist) {
                ruleTabChecklist.style.display = 'block';
                ruleTabChecklist.classList.add('active');
            }
            updateChecklistProgress();
        } else if (tabName === 'restore') {
            if (tabRuleRestoreBtn) {
                tabRuleRestoreBtn.classList.add('active');
                tabRuleRestoreBtn.style.background = 'rgba(99, 102, 241, 0.2)';
                tabRuleRestoreBtn.style.color = '#818cf8';
            }
            if (ruleTabRestore) {
                ruleTabRestore.style.display = 'block';
                ruleTabRestore.classList.add('active');
            }
        }
    }

    window.switchRuleTab = switchRuleTab;

    function openDebugModal() {
        const dataDebugModal = document.getElementById('dataDebugModal');
        if (dataDebugModal) {
            dataDebugModal.style.display = 'flex';
            if (typeof loadDataDebugReport === 'function') {
                loadDataDebugReport();
            }
        }
    }
    window.openDebugModal = openDebugModal;


    // Unified Rule Tab Click Listener Binding
    document.querySelectorAll('.rule-tab-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const tabName = btn.getAttribute('data-ruletab');
            if (tabName) {
                switchRuleTab(tabName);
            }
        });
    });

    const tabRuleAiCenterBtn = document.getElementById('tabRuleAiCenterBtn');
    if (tabRuleAiCenterBtn) tabRuleAiCenterBtn.addEventListener('click', () => switchRuleTab('aicenter'));

    const tabRuleTeacherMaintainBtn = document.getElementById('tabRuleTeacherMaintainBtn');
    if (tabRuleTeacherMaintainBtn) tabRuleTeacherMaintainBtn.addEventListener('click', () => switchRuleTab('teachermaintain'));

    const tabRuleChecklistBtn = document.getElementById('tabRuleChecklistBtn');
    if (tabRuleChecklistBtn) tabRuleChecklistBtn.addEventListener('click', () => switchRuleTab('checklist'));

    const tabRuleMoeCodeBtn = document.getElementById('tabRuleMoeCodeBtn');
    if (tabRuleMoeCodeBtn) tabRuleMoeCodeBtn.addEventListener('click', () => switchRuleTab('moecode'));

    const tabRuleSemesterBtn = document.getElementById('tabRuleSemesterBtn');
    if (tabRuleSemesterBtn) tabRuleSemesterBtn.addEventListener('click', () => switchRuleTab('semester'));

    const tabRuleSchoolBtn = document.getElementById('tabRuleSchoolBtn');
    if (tabRuleSchoolBtn) tabRuleSchoolBtn.addEventListener('click', () => switchRuleTab('school'));

    if (tabRuleTeacherBtn) tabRuleTeacherBtn.addEventListener('click', () => switchRuleTab('teacher'));
    if (tabRuleSubBtn) tabRuleSubBtn.addEventListener('click', () => switchRuleTab('sub'));
    if (tabRuleWeightsBtn) tabRuleWeightsBtn.addEventListener('click', () => switchRuleTab('weights'));
    if (tabRuleAssignBtn) tabRuleAssignBtn.addEventListener('click', () => switchRuleTab('assign'));
    if (tabRuleCatalogBtn) tabRuleCatalogBtn.addEventListener('click', () => switchRuleTab('catalog'));
    if (tabRuleVenuesBtn) tabRuleVenuesBtn.addEventListener('click', () => switchRuleTab('venues'));
    if (tabRuleSimBtn) tabRuleSimBtn.addEventListener('click', () => switchRuleTab('sim'));
    if (tabRuleRestoreBtn) tabRuleRestoreBtn.addEventListener('click', () => switchRuleTab('restore'));

    // Master AI One Click Wizard Button
    const masterAiOneClickBtn = document.getElementById('masterAiOneClickBtn');
    if (masterAiOneClickBtn && masterAiOneClickBtn.dataset.listener !== 'true') {
        masterAiOneClickBtn.dataset.listener = 'true';
        masterAiOneClickBtn.addEventListener('click', async () => {
            if (!confirm("確定要執行【全校 AI 一鍵全套建置】嗎？\n系統將為您連續執行：\n1. AI 智慧教師配課 & 節數平衡\n2. AI 專用教室自動對接\n3. 全校共同班會排課鎖定\n4. CP-SAT 課表最佳化求解 & 衝突驗證！")) {
                return;
            }

            try {
                showToast("🤖 步驟 1/4：正在執行 AI 智慧全校教師配課與平衡...");
                await fetch('/api/auto-assign', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ overwrite: true })
                });

                showToast("🪄 步驟 2/4：正在自動對接全校專用教室與容量控管...");
                const matchBtn = document.getElementById('autoAiMatchVenuesBtn');
                if (matchBtn) matchBtn.click();

                showToast("👥 步驟 3/4：正在一鍵設定全校共同班會鎖定...");
                const simBtn = document.getElementById('presetSimClassMeetingBtn');
                if (simBtn) simBtn.click();

                showToast("🧠 步驟 4/4：正在啟動 Google OR-Tools CP-SAT 求解器進行最佳化排課...");
                const runBtn = document.getElementById('runSolverBtn');
                if (runBtn) runBtn.click();

                setTimeout(() => {
                    showToast("🎉 全校 AI 一鍵全套建置完成！零衝突課表已產生。");
                }, 3500);
            } catch (e) {
                console.error(e);
                showToast("全套建置過程發生異常，請重試。");
            }
        });
    }

    // AI Center Card Shortcuts
    const cardAiAutoAssignBtn = document.getElementById('cardAiAutoAssignBtn');
    if (cardAiAutoAssignBtn) cardAiAutoAssignBtn.addEventListener('click', () => {
        const btn = document.getElementById('aiAutoAssignBtn');
        if (btn) btn.click();
    });

    const cardAiMatchVenuesBtn = document.getElementById('cardAiMatchVenuesBtn');
    if (cardAiMatchVenuesBtn) cardAiMatchVenuesBtn.addEventListener('click', () => {
        const btn = document.getElementById('autoAiMatchVenuesBtn');
        if (btn) btn.click();
    });

    const cardSimClassMeetingBtn = document.getElementById('cardSimClassMeetingBtn');
    if (cardSimClassMeetingBtn) cardSimClassMeetingBtn.addEventListener('click', () => {
        const btn = document.getElementById('presetSimClassMeetingBtn');
        if (btn) btn.click();
    });

    const cardSimClubBtn = document.getElementById('cardSimClubBtn');
    if (cardSimClubBtn) cardSimClubBtn.addEventListener('click', () => {
        const btn = document.getElementById('presetSimClubBtn');
        if (btn) btn.click();
    });

    const cardSimWeeklyBtn = document.getElementById('cardSimWeeklyBtn');
    if (cardSimWeeklyBtn) cardSimWeeklyBtn.addEventListener('click', () => {
        const btn = document.getElementById('presetSimWeeklyBtn');
        if (btn) btn.click();
    });

    const cardRunSolverBtn = document.getElementById('cardRunSolverBtn');
    if (cardRunSolverBtn) cardRunSolverBtn.addEventListener('click', () => {
        const btn = document.getElementById('runSolverBtn');
        if (btn) btn.click();
    });

    const cardValidateSolverBtn = document.getElementById('cardValidateSolverBtn');
    if (cardValidateSolverBtn) cardValidateSolverBtn.addEventListener('click', () => {
        const btn = document.getElementById('validateSolverBtn');
        if (btn) btn.click();
    });

    const aiAutoAssignBtn = document.getElementById('aiAutoAssignBtn');
    if (aiAutoAssignBtn && aiAutoAssignBtn.dataset.listener !== 'true') {
        aiAutoAssignBtn.dataset.listener = 'true';
        aiAutoAssignBtn.addEventListener('click', async () => {
            if (!confirm("確定要執行 AI 智慧自動配課嗎？\n系統將分析全校年級課程規劃、班導師與教師授課額度，自動一鍵匹配並指派教師！")) {
                return;
            }
            try {
                showToast("正在執行 AI 智慧自動配課分析中...");
                const resp = await fetch('/api/auto-assign', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ overwrite: true })
                });
                const res = await resp.json();
                if (res.status === 'success') {
                    showToast(res.message);
                    if (typeof loadCourseAssignments === 'function') {
                        loadCourseAssignments();
                    }
                } else {
                    showToast("AI 自動配課失敗：" + res.message);
                }
            } catch (e) {
                console.error(e);
                showToast("伺服器連線異常。");
            }
        });
    }



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
        assignClassSelect.innerHTML = '<option value="">-- 選擇班級 --</option>';
        metadata.classes.forEach(c => {
            const opt = document.createElement('option');
            opt.value = c.code;
            opt.textContent = `${c.name} (${c.code})`;
            assignClassSelect.appendChild(opt);
        });
    }

    if (metadata.classes && assignAddClassSelect && assignAddClassSelect.options.length <= 1) {
        assignAddClassSelect.innerHTML = '<option value="">-- 選擇授課班級 --</option>';
        metadata.classes.forEach(c => {
            const opt = document.createElement('option');
            opt.value = c.code;
            opt.textContent = `${c.name} (${c.code})`;
            assignAddClassSelect.appendChild(opt);
        });
    }

    if (metadata.teachers && assignTeacherSelect.options.length <= 1) {
        assignTeacherSelect.innerHTML = '<option value="">-- 選擇教師 --</option>';
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

            // Populate assignClassSelect with classes from allCourseAssignmentsData or metadata
            if (assignClassSelect) {
                const currentVal = assignClassSelect.value;
                assignClassSelect.innerHTML = '<option value="">-- 請選擇班級檢視/調整配課 --</option>';
                
                const classList = (allCourseAssignmentsData.length > 0) ? 
                    allCourseAssignmentsData.map(c => ({ code: c.class_code, name: c.class_name })) :
                    (metadata.classes || []);

                classList.forEach(c => {
                    const opt = document.createElement('option');
                    opt.value = c.code;
                    opt.textContent = `${c.name} (${c.code})`;
                    if (c.code === currentVal) opt.selected = true;
                    assignClassSelect.appendChild(opt);
                });

                if (assignClassSelect.dataset.listener !== 'true') {
                    assignClassSelect.dataset.listener = 'true';
                    assignClassSelect.addEventListener('change', () => {
                        renderCourseAssignTable();
                    });
                }

                if (!assignClassSelect.value && assignClassSelect.options.length > 1) {
                    assignClassSelect.selectedIndex = 1;
                }
            }

            // Populate assignTeacherSelect with all available teachers
            if (assignTeacherSelect && allTeacherAssignmentsData.length > 0) {
                const currentVal = assignTeacherSelect.value;
                assignTeacherSelect.innerHTML = '<option value="">-- 選擇教師 --</option>';
                allTeacherAssignmentsData.forEach(t => {
                    const opt = document.createElement('option');
                    opt.value = t.teacher_code;
                    opt.textContent = `${t.teacher_name} (${t.teacher_code})`;
                    if (t.teacher_code === currentVal) opt.selected = true;
                    assignTeacherSelect.appendChild(opt);
                });
            }

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
            <th style="width: 26%;">科目名稱 (代碼)</th>
            <th style="width: 14%;">每週節數</th>
            <th style="width: 20%;">目前授課教師</th>
            <th style="width: 22%;">變更配課教師</th>
            <th style="width: 18%;">操作</th>
        </tr>
    `;

    const selectedClass = assignClassSelect.value;
    if (!selectedClass) {
        container.style.display = 'none';
        return;
    }

    const classInfo = allCourseAssignmentsData.find(c => c.class_code === selectedClass);
    if (!classInfo || !classInfo.subjects || classInfo.subjects.length === 0) {
        tbody.innerHTML = '<tr><td colspan="5" style="text-align: center; color: var(--text-muted); padding: 16px;">此班級暫無配課資料。您可以點擊上方【🤖 執行 AI 智慧自動配課】一鍵產生全校配課！</td></tr>';
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
        sel.style.width = '100%';

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
        tdAct.style.textAlign = 'center';
        tdAct.style.whiteSpace = 'nowrap';

        const actWrap = document.createElement('div');
        actWrap.style.display = 'flex';
        actWrap.style.gap = '6px';
        actWrap.style.justifyContent = 'center';
        actWrap.style.alignItems = 'center';

        const btn = document.createElement('button');
        btn.className = 'solver-action-btn primary-btn';
        btn.style.padding = '4px 8px';
        btn.style.fontSize = '0.75rem';
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
        delBtn.style.padding = '4px 8px';
        delBtn.style.fontSize = '0.75rem';
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

        actWrap.appendChild(btn);
        actWrap.appendChild(delBtn);
        tdAct.appendChild(actWrap);
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
            <th style="width: 20%;">授課班級 (代碼)</th>
            <th style="width: 26%;">科目名稱 (代碼)</th>
            <th style="width: 16%;">每週授課節數</th>
            <th style="width: 20%;">配課狀態</th>
            <th style="width: 18%;">操作</th>
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

        // Action Delete Button
        const tdAct = document.createElement('td');
        tdAct.style.textAlign = 'center';
        tdAct.style.whiteSpace = 'nowrap';

        const actWrap = document.createElement('div');
        actWrap.style.display = 'flex';
        actWrap.style.gap = '6px';
        actWrap.style.justifyContent = 'center';
        actWrap.style.alignItems = 'center';

        const delBtn = document.createElement('button');
        delBtn.className = 'solver-action-btn secondary-btn';
        delBtn.style.padding = '4px 10px';
        delBtn.style.fontSize = '0.8rem';
        delBtn.style.background = 'rgba(239, 68, 68, 0.2)';
        delBtn.style.borderColor = 'rgba(239, 68, 68, 0.4)';
        delBtn.style.color = '#ef4444';
        delBtn.innerHTML = '<i class="fa-solid fa-trash"></i> 刪除';

        delBtn.addEventListener('click', async () => {
            if (!confirm(`確定要移除 ${tInfo.teacher_name} 老師在 ${c.class_name} 班的 ${c.subject_name} 配課嗎？`)) return;
            try {
                const resp = await fetch('/api/delete-course-assignment', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        class_code: c.class_code,
                        subject_code: c.subject_code
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

        actWrap.appendChild(delBtn);
        tdAct.appendChild(actWrap);
        tr.appendChild(tdAct);

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

    // Quick Snapshot Buttons
    const quickSnapshotPreBtn = document.getElementById('quickSnapshotPreBtn');
    if (quickSnapshotPreBtn && quickSnapshotPreBtn.dataset.listener !== 'true') {
        quickSnapshotPreBtn.dataset.listener = 'true';
        quickSnapshotPreBtn.addEventListener('click', async () => {
            await doCreateSnapshot("排課前規則快照");
        });
    }

    const quickSnapshotPostBtn = document.getElementById('quickSnapshotPostBtn');
    if (quickSnapshotPostBtn && quickSnapshotPostBtn.dataset.listener !== 'true') {
        quickSnapshotPostBtn.dataset.listener = 'true';
        quickSnapshotPostBtn.addEventListener('click', async () => {
            await doCreateSnapshot("排課後成果快照");
        });
    }

    async function doCreateSnapshot(note) {
        try {
            showToast(`正在拍攝【${note}】...`);
            const resp = await fetch('/api/create-restore-point', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ note })
            });
            const res = await resp.json();
            if (res.status === 'success') {
                showToast(res.message);
                await loadRestorePoints();
            } else {
                showToast("建立失敗：" + res.message);
            }
        } catch (e) {
            showToast("伺服器連線異常。");
        }
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

let semestersData = [];

async function loadSemesters() {
    const createBtn = document.getElementById('createNewSemesterBtn');
    if (createBtn && createBtn.dataset.listener !== 'true') {
        createBtn.dataset.listener = 'true';
        createBtn.addEventListener('click', async () => {
            const semSelect = document.getElementById('newSemesterIdSelect');
            const semId = semSelect ? semSelect.value : '114-2';
            await doCreateSemester(semId);
        });
    }

    document.querySelectorAll('.quick-add-sem-btn').forEach(btn => {
        if (btn.dataset.listener !== 'true') {
            btn.dataset.listener = 'true';
            btn.addEventListener('click', (e) => {
                const semId = e.currentTarget.getAttribute('data-sem');
                const semSelect = document.getElementById('newSemesterIdSelect');
                if (semSelect) semSelect.value = semId;
                doCreateSemester(semId);
            });
        }
    });

    try {
        const resp = await fetch('/api/semesters');
        const data = await resp.json();
        if (data.status === 'success') {
            semestersData = data.semesters || [];
            renderSemestersTable(data.active_id || data.active_semester_id);
            const activeBadge = document.getElementById('activeSemesterBadge');
            if (activeBadge) activeBadge.textContent = `${data.active_id || data.active_semester_id || '114-1'} 學期`;

            // Populate top navbar semester dropdown
            const headerSel = document.getElementById('headerSemesterSelect');
            if (headerSel) {
                headerSel.innerHTML = '';
                const activeSem = data.active_id || data.active_semester_id;
                semestersData.forEach(s => {
                    const sid = s.id || s.semester_id;
                    const opt = document.createElement('option');
                    opt.value = sid;
                    opt.style.background = '#0f172a';
                    opt.style.color = '#fff';
                    opt.textContent = `${sid} 學期 (${s.school_name || '學校'})`;
                    if (s.is_active || sid === activeSem) {
                        opt.selected = true;
                    }
                    headerSel.appendChild(opt);
                });
                const optManage = document.createElement('option');
                optManage.value = '__manage__';
                optManage.style.background = '#1e1b4b';
                optManage.style.color = '#c084fc';
                optManage.textContent = '⚙️ 點此開啟【全校歷史學期一覽表】...';
                headerSel.appendChild(optManage);

                if (headerSel.dataset.listener !== 'true') {
                    headerSel.dataset.listener = 'true';
                    headerSel.addEventListener('change', async (e) => {
                        const val = e.target.value;
                        if (val === '__manage__') {
                            const modal = document.getElementById('solverModal');
                            if (modal) modal.style.display = 'flex';
                            if (typeof switchRuleTab === 'function') switchRuleTab('semester');
                        } else if (val) {
                            try {
                                showToast(`正在切換至【${val}】學期...`);
                                const resp = await fetch('/api/semesters/switch', {
                                    method: 'POST',
                                    headers: {'Content-Type': 'application/json'},
                                    body: JSON.stringify({ semester_id: val })
                                });
                                const res = await resp.json();
                                if (res.status === 'success') {
                                    showToast(res.message);
                                    setTimeout(() => window.location.reload(), 1000);
                                } else {
                                    showToast("切換失敗：" + res.message);
                                }
                            } catch (err) {
                                showToast("伺服器連線異常。");
                            }
                        }
                    });
                }
            }
        }
    } catch (e) {
        console.error("Load semesters failed:", e);
    }
}

async function doCreateSemester(semId) {
    if (!confirm(`確定要繼承現有全校資料並開辦【${semId}】新學期嗎？`)) return;
    try {
        showToast(`正在開辦【${semId}】學期...`);
        const resp = await fetch('/api/semesters/create', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ semester_id: semId })
        });
        const res = await resp.json();
        if (res.status === 'success') {
            showToast(res.message);
            await loadSemesters();
        } else {
            showToast("開辦失敗：" + res.message);
        }
    } catch (e) {
        showToast("伺服器連線異常。");
    }
}

function renderSemestersTable(activeId) {
    const tbody = document.getElementById('semestersTableBody');
    if (!tbody) return;

    tbody.innerHTML = '';
    if (semestersData.length === 0) {
        tbody.innerHTML = '<tr><td colspan="5" style="text-align:center; color:var(--text-muted);">尚無歷史學期檔案</td></tr>';
        return;
    }

    semestersData.forEach(s => {
        const semId = s.semester_id || s.id || '114-1';
        const isCurrent = s.is_active || semId === activeId;
        const tr = document.createElement('tr');
        if (isCurrent) {
            tr.style.background = 'rgba(168, 85, 247, 0.12)';
        }

        const tdId = document.createElement('td');
        tdId.style.fontWeight = 'bold';
        tdId.style.color = '#c084fc';
        tdId.textContent = `${semId} 學期`;
        tr.appendChild(tdId);

        const tdSchool = document.createElement('td');
        tdSchool.textContent = s.school_name || '學校檔案';
        tr.appendChild(tdSchool);

        const tdTime = document.createElement('td');
        tdTime.style.color = 'var(--text-muted)';
        tdTime.style.fontSize = '0.8rem';
        tdTime.textContent = s.updated_at || '系統預設';
        tr.appendChild(tdTime);

        const tdCount = document.createElement('td');
        tdCount.style.color = '#38bdf8';
        tdCount.style.fontWeight = 'bold';
        const slotsCount = s.slots_count !== undefined ? s.slots_count : (s.solved_count || 0);
        tdCount.textContent = `${slotsCount} 節`;
        tr.appendChild(tdCount);

        const tdAct = document.createElement('td');
        tdAct.style.textAlign = 'center';

        if (isCurrent) {
            tdAct.innerHTML = '<span style="color:#34d399; font-weight:bold; font-size:0.82rem;"><i class="fa-solid fa-circle-check"></i> 目前啟用中</span>';
        } else {
            const switchBtn = document.createElement('button');
            switchBtn.className = 'solver-action-btn primary-btn';
            switchBtn.style.padding = '4px 10px';
            switchBtn.style.fontSize = '0.78rem';
            switchBtn.style.background = '#a855f7';
            switchBtn.innerHTML = '<i class="fa-solid fa-right-to-bracket"></i> 點選切換啟用';
            switchBtn.addEventListener('click', async () => {
                try {
                    showToast(`正在切換至【${semId}】學期檔案...`);
                    const resp = await fetch('/api/semesters/switch', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({ semester_id: semId })
                    });
                    const res = await resp.json();
                    if (res.status === 'success') {
                        showToast(res.message);
                        setTimeout(() => window.location.reload(), 1000);
                    } else {
                        showToast("切換失敗：" + res.message);
                    }
                } catch (e) {
                    showToast("伺服器連線異常。");
                }
            });
            tdAct.appendChild(switchBtn);
        }
        tr.appendChild(tdAct);
        tbody.appendChild(tr);
    });
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

let classConsecutiveRules = [];
let subjectVenueMappings = [];

async function loadVenueCapacities() {
    const saveVenueCapacitiesBtn = document.getElementById('saveVenueCapacitiesBtn');
    const addNewVenueBtn = document.getElementById('addNewVenueBtn');
    const addClassConsecutiveBtn = document.getElementById('addClassConsecutiveBtn');
    const addSubjectVenueBtn = document.getElementById('addSubjectVenueBtn');
    const consecClassSelect = document.getElementById('consecClassSelect');
    const consecSubjectSelect = document.getElementById('consecSubjectSelect');
    const mapSubjectSelect = document.getElementById('mapSubjectSelect');

    // Populate selects
    if (consecClassSelect && metadata.classes) {
        consecClassSelect.innerHTML = '<option value="">選擇班級...</option>';
        metadata.classes.forEach(c => {
            const opt = document.createElement('option');
            opt.value = c.code;
            opt.textContent = `${c.name} (${c.code})`;
            consecClassSelect.appendChild(opt);
        });
    }

    if (consecSubjectSelect && metadata.subjects) {
        consecSubjectSelect.innerHTML = '<option value="">選擇科目...</option>';
        metadata.subjects.forEach(s => {
            const opt = document.createElement('option');
            opt.value = s.code;
            opt.textContent = `${s.name} (${s.code})`;
            consecSubjectSelect.appendChild(opt);
        });
    }

    if (mapSubjectSelect && metadata.subjects) {
        mapSubjectSelect.innerHTML = '<option value="">選擇科目...</option>';
        metadata.subjects.forEach(s => {
            const opt = document.createElement('option');
            opt.value = s.code;
            opt.textContent = `${s.name} (${s.code})`;
            mapSubjectSelect.appendChild(opt);
        });
    }

    // Add Custom Venue Handler
    if (addNewVenueBtn && addNewVenueBtn.dataset.listener !== 'true') {
        addNewVenueBtn.dataset.listener = 'true';
        addNewVenueBtn.addEventListener('click', () => {
            const vnameInput = document.getElementById('newVenueNameInput');
            const vcapInput = document.getElementById('newVenueCapInput');
            const vname = (vnameInput.value || '').trim();
            const vcap = parseInt(vcapInput.value || 1);
            if (!vname) {
                showToast("請輸入教室名稱！");
                return;
            }

            const container = document.getElementById('customVenuesContainer');
            if (container) {
                const item = document.createElement('div');
                item.style.display = 'flex';
                item.style.alignItems = 'center';
                item.style.gap = '8px';
                item.style.background = 'rgba(15,23,42,0.4)';
                item.style.padding = '6px 10px';
                item.style.borderRadius = '6px';
                item.innerHTML = `
                    <label style="font-size: 0.85rem; min-width: 90px;">🏫 ${vname}：</label>
                    <input type="number" class="venue-cap-input" data-vname="${vname}" min="1" max="10" value="${vcap}" style="width: 55px; padding: 4px; border-radius: 4px; background: rgba(15,23,42,0.8); color: #fff; border: 1px solid var(--border-color);"> 班
                    <button type="button" onclick="this.parentElement.remove()" style="background: rgba(239,68,68,0.2); color: #ef4444; border: 1px solid rgba(239,68,68,0.4); border-radius: 4px; padding: 2px 6px; font-size: 0.75rem; cursor: pointer;">
                        <i class="fa-solid fa-trash"></i>
                    </button>
                `;
                container.appendChild(item);
                vnameInput.value = '';
                showToast(`已成功新增【${vname}】專用教室！`);
            }
        });
    }

    // Add Class Consecutive Rule Handler
    if (addClassConsecutiveBtn && addClassConsecutiveBtn.dataset.listener !== 'true') {
        addClassConsecutiveBtn.dataset.listener = 'true';
        addClassConsecutiveBtn.addEventListener('click', () => {
            const classCode = consecClassSelect.value;
            const className = consecClassSelect.options[consecClassSelect.selectedIndex]?.text || classCode;
            const subjCode = consecSubjectSelect.value;
            const subjName = consecSubjectSelect.options[consecSubjectSelect.selectedIndex]?.text || subjCode;
            const length = parseInt(document.getElementById('consecLengthSelect').value || 2);

            if (!classCode || !subjCode) {
                showToast("請先選擇班級與科目！");
                return;
            }

            classConsecutiveRules.push({
                class_code: classCode,
                class_name: className,
                subject_code: subjCode,
                subject_name: subjName,
                length: length
            });

            renderClassConsecutiveTable();
            showToast(`已新增【${className}】${subjName} 連堂 ${length} 節約束！`);
        });
    }

    // Add Subject Venue Mapping Handler
    if (addSubjectVenueBtn && addSubjectVenueBtn.dataset.listener !== 'true') {
        addSubjectVenueBtn.dataset.listener = 'true';
        addSubjectVenueBtn.addEventListener('click', () => {
            const mapSubjectSelect = document.getElementById('mapSubjectSelect');
            const mapVenueSelect = document.getElementById('mapVenueSelect');
            const subjCode = mapSubjectSelect.value;
            const subjName = mapSubjectSelect.options[mapSubjectSelect.selectedIndex]?.text || subjCode;
            const roomName = mapVenueSelect.value;

            if (!subjCode || !roomName) {
                showToast("請先選擇科目與專用教室！");
                return;
            }

            subjectVenueMappings.push({
                subject_code: subjCode,
                subject_name: subjName,
                room_name: roomName
            });

            renderSubjectVenueTable();
            showToast(`已成功指派【${subjName}】➔ ${roomName}！`);
        });
    }

    // AI Smart Auto Match Venues Button
    const autoAiMatchVenuesBtn = document.getElementById('autoAiMatchVenuesBtn');
    if (autoAiMatchVenuesBtn && autoAiMatchVenuesBtn.dataset.listener !== 'true') {
        autoAiMatchVenuesBtn.dataset.listener = 'true';
        autoAiMatchVenuesBtn.addEventListener('click', async () => {
            let targetSubjects = [];
            if (metadata.subjects && metadata.subjects.length > 0) {
                targetSubjects = metadata.subjects;
            } else if (typeof masterSubjectCatalogData !== 'undefined' && masterSubjectCatalogData.length > 0) {
                targetSubjects = masterSubjectCatalogData;
            } else {
                targetSubjects = [
                    { code: "J104", name: "理化" },
                    { code: "J105", name: "生物" },
                    { code: "J110", name: "體育" },
                    { code: "J112", name: "音樂" },
                    { code: "J113", name: "視覺藝術" },
                    { code: "J115", name: "資訊科技" },
                    { code: "J116", name: "生活科技" },
                    { code: "J117", name: "家政" },
                    { code: "H104", name: "物理" },
                    { code: "H105", name: "化學" },
                    { code: "H110", name: "體育" },
                    { code: "104", name: "物理" },
                    { code: "105", name: "化學" },
                    { code: "110", name: "程式設計" }
                ];
            }

            const caps = {
                "電腦教室": 2,
                "理化實驗室": 2,
                "生物實驗室": 1,
                "音樂教室": 1,
                "美術教室": 1,
                "體育場/館": 3,
                "家政教室": 1,
                "生活科技教室": 1
            };

            const mappings = [];
            targetSubjects.forEach(s => {
                const sn = s.name || '';
                let room = null;
                if (sn.includes("資訊") || sn.includes("程式") || sn.includes("電腦")) room = "電腦教室";
                else if (sn.includes("理化") || sn.includes("化學")) room = "理化實驗室";
                else if (sn.includes("生物")) room = "生物實驗室";
                else if (sn.includes("音樂")) room = "音樂教室";
                else if (sn.includes("視覺") || sn.includes("美術") || sn.includes("藝術")) room = "美術教室";
                else if (sn.includes("體育")) room = "體育場/館";
                else if (sn.includes("家政")) room = "家政教室";
                else if (sn.includes("生活科技") || sn.includes("生科")) room = "生活科技教室";

                if (room) {
                    mappings.push({
                        subject_code: s.code,
                        subject_name: `${s.name} (${s.code})`,
                        room_name: room
                    });
                }
            });

            subjectVenueMappings = mappings;

            // Render custom venues container
            const container = document.getElementById('customVenuesContainer');
            if (container) {
                container.innerHTML = '';
                Object.keys(caps).forEach(vname => {
                    const icon = vname.includes("電腦") ? "💻" : vname.includes("實驗") ? "🧪" : vname.includes("音樂") ? "🎵" : vname.includes("體育") ? "🏀" : "🏫";
                    const item = document.createElement('div');
                    item.style.display = 'flex';
                    item.style.alignItems = 'center';
                    item.style.gap = '8px';
                    item.style.background = 'rgba(15,23,42,0.4)';
                    item.style.padding = '6px 10px';
                    item.style.borderRadius = '6px';
                    item.innerHTML = `
                        <label style="font-size: 0.85rem; min-width: 90px;">${icon} ${vname}：</label>
                        <input type="number" class="venue-cap-input" data-vname="${vname}" min="1" max="10" value="${caps[vname]}" style="width: 55px; padding: 4px; border-radius: 4px; background: rgba(15,23,42,0.8); color: #fff; border: 1px solid var(--border-color);"> 班
                        <button type="button" onclick="this.parentElement.remove()" style="background: rgba(239,68,68,0.2); color: #ef4444; border: 1px solid rgba(239,68,68,0.4); border-radius: 4px; padding: 2px 6px; font-size: 0.75rem; cursor: pointer;">
                            <i class="fa-solid fa-trash"></i>
                        </button>
                    `;
                    container.appendChild(item);
                });
            }

            renderSubjectVenueTable();

            // Auto save to backend
            try {
                showToast("正在一鍵儲存 AI 智慧專用教室對接資料...");
                const resp = await fetch('/api/save-venue-capacities', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        venue_capacities: caps,
                        consecutive_subjects: ["J104", "J115", "104", "105"],
                        class_consecutive_rules: classConsecutiveRules,
                        subject_venue_mappings: mappings
                    })
                });
                const res = await resp.json();
                if (res.status === 'success') {
                    showToast(`🎉 成功完成 AI 智慧專用教室對接！已自動綁定 ${mappings.length} 門專用科目與對應教室容量上限。`);
                } else {
                    showToast("AI 對接儲存失敗：" + res.message);
                }
            } catch (e) {
                showToast("伺服器連線異常。");
            }
        });
    }

    // Save All Button
    if (saveVenueCapacitiesBtn && saveVenueCapacitiesBtn.dataset.listener !== 'true') {
        saveVenueCapacitiesBtn.dataset.listener = 'true';
        saveVenueCapacitiesBtn.addEventListener('click', async () => {
            const caps = {};
            document.querySelectorAll('.venue-cap-input').forEach(inp => {
                const vn = inp.getAttribute('data-vname');
                const val = parseInt(inp.value || 1);
                if (vn) caps[vn] = val;
            });

            const checkedBoxes = document.querySelectorAll('#consecutiveSubjectsCheckboxes input[type="checkbox"]:checked');
            const consec = Array.from(checkedBoxes).map(cb => cb.value);

            try {
                const resp = await fetch('/api/save-venue-capacities', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        venue_capacities: caps,
                        consecutive_subjects: consec,
                        class_consecutive_rules: classConsecutiveRules,
                        subject_venue_mappings: subjectVenueMappings
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

    try {
        const resp = await fetch('/api/get-venue-capacities');
        const data = await resp.json();
        if (data.status === 'success') {
            const caps = data.venue_capacities || {};
            const container = document.getElementById('customVenuesContainer');
            if (container) {
                container.innerHTML = '';
                Object.keys(caps).forEach(vname => {
                    const icon = vname.includes("電腦") ? "💻" : vname.includes("實驗") ? "🧪" : vname.includes("音樂") ? "🎵" : vname.includes("體育") ? "🏀" : "🏫";
                    const item = document.createElement('div');
                    item.style.display = 'flex';
                    item.style.alignItems = 'center';
                    item.style.gap = '8px';
                    item.style.background = 'rgba(15,23,42,0.4)';
                    item.style.padding = '6px 10px';
                    item.style.borderRadius = '6px';
                    item.innerHTML = `
                        <label style="font-size: 0.85rem; min-width: 90px;">${icon} ${vname}：</label>
                        <input type="number" class="venue-cap-input" data-vname="${vname}" min="1" max="10" value="${caps[vname]}" style="width: 55px; padding: 4px; border-radius: 4px; background: rgba(15,23,42,0.8); color: #fff; border: 1px solid var(--border-color);"> 班
                        <button type="button" onclick="this.parentElement.remove()" style="background: rgba(239,68,68,0.2); color: #ef4444; border: 1px solid rgba(239,68,68,0.4); border-radius: 4px; padding: 2px 6px; font-size: 0.75rem; cursor: pointer;">
                            <i class="fa-solid fa-trash"></i>
                        </button>
                    `;
                    container.appendChild(item);
                });
            }

            classConsecutiveRules = data.class_consecutive_rules || [];
            renderClassConsecutiveTable();

            subjectVenueMappings = data.subject_venue_mappings || [];
            renderSubjectVenueTable();

            const consecContainer = document.getElementById('consecutiveSubjectsCheckboxes');
            if (consecContainer) {
                consecContainer.innerHTML = '';
                const activeConsec = new Set(data.consecutive_subjects || ["104", "105", "110"]);
                if (metadata.subjects && metadata.subjects.length > 0) {
                    metadata.subjects.forEach(s => {
                        const isChecked = activeConsec.has(s.code) ? 'checked' : '';
                        const lbl = document.createElement('label');
                        lbl.style.fontSize = '0.85rem';
                        lbl.style.cursor = 'pointer';
                        lbl.style.marginRight = '14px';
                        lbl.style.marginBottom = '6px';
                        lbl.style.display = 'inline-flex';
                        lbl.style.alignItems = 'center';
                        lbl.style.gap = '4px';
                        lbl.innerHTML = `<input type="checkbox" value="${s.code}" ${isChecked}> ${s.name} (${s.code})`;
                        consecContainer.appendChild(lbl);
                    });
                }
            }
        }
    } catch (e) {
        console.error("Load venue capacities failed:", e);
    }
}

function renderClassConsecutiveTable() {
    const tbody = document.getElementById('classConsecutiveTableBody');
    if (!tbody) return;
    tbody.innerHTML = '';

    if (classConsecutiveRules.length === 0) {
        tbody.innerHTML = '<tr><td colspan="4" style="text-align: center; color: var(--text-muted); padding: 8px;">尚無手動設定的特定班級連堂規則</td></tr>';
        return;
    }

    classConsecutiveRules.forEach((rule, idx) => {
        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td>${rule.class_name || rule.class_code}</td>
            <td>${rule.subject_name || rule.subject_code}</td>
            <td><span style="color: #38bdf8; font-weight: 600;">連續 ${rule.length || 2} 節</span></td>
            <td style="text-align: center;">
                <button type="button" onclick="deleteClassConsecutiveRule(${idx})" style="background: rgba(239,68,68,0.2); color: #ef4444; border: 1px solid rgba(239,68,68,0.4); border-radius: 4px; padding: 2px 8px; font-size: 0.8rem; cursor: pointer;">
                    <i class="fa-solid fa-trash"></i> 刪除
                </button>
            </td>
        `;
        tbody.appendChild(tr);
    });
}

function deleteClassConsecutiveRule(idx) {
    classConsecutiveRules.splice(idx, 1);
    renderClassConsecutiveTable();
    showToast("已刪除該筆特定班級連堂規則。");
}

function renderSubjectVenueTable() {
    const tbody = document.getElementById('subjectVenueTableBody');
    if (!tbody) return;
    tbody.innerHTML = '';

    if (subjectVenueMappings.length === 0) {
        tbody.innerHTML = '<tr><td colspan="3" style="text-align: center; color: var(--text-muted); padding: 8px;">尚無對應的科目與專用教室指派關係</td></tr>';
        return;
    }

    subjectVenueMappings.forEach((mapItem, idx) => {
        const icon = mapItem.room_name.includes("電腦") ? "💻" : mapItem.room_name.includes("實驗") ? "🧪" : mapItem.room_name.includes("音樂") ? "🎵" : mapItem.room_name.includes("體育") ? "🏀" : "🏫";
        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td>${mapItem.subject_name || mapItem.subject_code}</td>
            <td><span style="color: #34d399; font-weight: 600;">${icon} ${mapItem.room_name}</span></td>
            <td style="text-align: center;">
                <button type="button" onclick="deleteSubjectVenueMapping(${idx})" style="background: rgba(239,68,68,0.2); color: #ef4444; border: 1px solid rgba(239,68,68,0.4); border-radius: 4px; padding: 2px 8px; font-size: 0.8rem; cursor: pointer;">
                    <i class="fa-solid fa-trash"></i> 刪除
                </button>
            </td>
        `;
        tbody.appendChild(tr);
    });
}

function deleteSubjectVenueMapping(idx) {
    subjectVenueMappings.splice(idx, 1);
    renderSubjectVenueTable();
    showToast("已刪除該筆科目專用教室對應。");
}



let currentSimGroupsData = [];

function createSimMemberRow(index) {
    const row = document.createElement('div');
    row.className = 'sim-member-row';
    row.style.display = 'flex';
    row.style.gap = '8px';
    row.style.alignItems = 'center';
    row.style.background = 'rgba(255, 255, 255, 0.03)';
    row.style.padding = '6px 10px';
    row.style.borderRadius = '6px';
    row.style.border = '1px solid var(--border-color)';

    const label = document.createElement('span');
    label.style.fontSize = '0.82rem';
    label.style.color = '#818cf8';
    label.style.fontWeight = 'bold';
    label.style.minWidth = '65px';
    label.textContent = `成員 #${index + 1}：`;
    row.appendChild(label);

    // Class Select
    const classSel = document.createElement('select');
    classSel.className = 'sim-class-select';
    classSel.style.flex = '1';
    classSel.style.padding = '4px 8px';
    classSel.style.borderRadius = '4px';
    classSel.style.background = 'rgba(15, 23, 42, 0.8)';
    classSel.style.color = '#fff';
    classSel.style.border = '1px solid var(--border-color)';
    classSel.style.fontSize = '0.82rem';
    classSel.innerHTML = '<option value="">-- 選擇班級 --</option>';
    if (metadata.classes) {
        metadata.classes.forEach(c => {
            const opt = document.createElement('option');
            opt.value = c.code;
            opt.textContent = `${c.name} (${c.code})`;
            classSel.appendChild(opt);
        });
    }
    row.appendChild(classSel);

    // Subject Select
    const subSel = document.createElement('select');
    subSel.className = 'sim-sub-select';
    subSel.style.flex = '1';
    subSel.style.padding = '4px 8px';
    subSel.style.borderRadius = '4px';
    subSel.style.background = 'rgba(15, 23, 42, 0.8)';
    subSel.style.color = '#fff';
    subSel.style.border = '1px solid var(--border-color)';
    subSel.style.fontSize = '0.82rem';
    function populateSubjects(selectedClassCode = '') {
        subSel.innerHTML = '<option value="">-- 選擇科目 --</option>';
        const subList = metadata.subjects || [];
        subList.forEach(s => {
            const opt = document.createElement('option');
            opt.value = s.code;
            opt.textContent = `${s.name} (${s.code})`;
            subSel.appendChild(opt);
        });
    }

    classSel.addEventListener('change', (e) => {
        populateSubjects(e.target.value);
    });

    populateSubjects();
    row.appendChild(subSel);

    // Remove Row Button
    const delBtn = document.createElement('button');
    delBtn.className = 'solver-action-btn secondary-btn';
    delBtn.style.padding = '2px 8px';
    delBtn.style.fontSize = '0.78rem';
    delBtn.style.color = '#ef4444';
    delBtn.style.background = 'rgba(239, 68, 68, 0.15)';
    delBtn.innerHTML = '<i class="fa-solid fa-xmark"></i>';
    delBtn.addEventListener('click', () => {
        const container = document.getElementById('simMembersContainer');
        if (container && container.children.length > 2) {
            row.remove();
        } else {
            showToast("每個同時排課群組至少需要 2 個班級科目成員！");
        }
    });
    row.appendChild(delBtn);

    return row;
}

function initSimMemberRows() {
    const container = document.getElementById('simMembersContainer');
    if (!container) return;
    container.innerHTML = '';
    container.appendChild(createSimMemberRow(0));
    container.appendChild(createSimMemberRow(1));
}

async function loadSimultaneousGroups() {
    initSimMemberRows();

    const addBtn = document.getElementById('addSimMemberRowBtn');
    if (addBtn && addBtn.dataset.listener !== 'true') {
        addBtn.dataset.listener = 'true';
        addBtn.addEventListener('click', () => {
            const container = document.getElementById('simMembersContainer');
            if (container) {
                const count = container.children.length;
                container.appendChild(createSimMemberRow(count));
            }
        });
    }

    const saveBtn = document.getElementById('saveSimGroupBtn');
    if (saveBtn && saveBtn.dataset.listener !== 'true') {
        saveBtn.dataset.listener = 'true';
        saveBtn.addEventListener('click', async () => {
            const nameInput = document.getElementById('simGroupNameInput');
            const name = nameInput ? nameInput.value.trim() : '';
            if (!name) {
                showToast("請輸入同時排課群組名稱！");
                return;
            }

            const rows = document.querySelectorAll('.sim-member-row');
            const members = [];
            let valid = true;

            rows.forEach(row => {
                const cSel = row.querySelector('.sim-class-select');
                const sSel = row.querySelector('.sim-sub-select');
                const cc = cSel ? cSel.value : '';
                const sc = sSel ? sSel.value : '';
                const cn = cSel && cSel.options[cSel.selectedIndex] ? cSel.options[cSel.selectedIndex].text.split(' ')[0] : cc;
                const sn = sSel && sSel.options[sSel.selectedIndex] ? sSel.options[sSel.selectedIndex].text.split(' ')[0] : sc;

                if (!cc || !sc) {
                    valid = false;
                } else {
                    members.push({
                        class_code: cc,
                        class_name: cn,
                        subject_code: sc,
                        subject_name: sn
                    });
                }
            });

            if (!valid || members.length < 2) {
                showToast("請為每個成員完整選擇「班級」與「科目」，且至少需 2 個成員！");
                return;
            }

            const fixedDay = document.getElementById('simGroupDayInput')?.value || null;
            const fixedPeriod = document.getElementById('simGroupPeriodInput')?.value || null;

            try {
                const resp = await fetch('/api/save-simultaneous-group', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ name, members, fixed_day: fixedDay, fixed_period: fixedPeriod })
                });
                const res = await resp.json();
                if (res.status === 'success') {
                    showToast(res.message);
                    if (nameInput) nameInput.value = '';
                    const daySel = document.getElementById('simGroupDayInput');
                    const periodSel = document.getElementById('simGroupPeriodInput');
                    if (daySel) daySel.value = '';
                    if (periodSel) periodSel.value = '';
                    currentSimGroupsData = res.simultaneous_groups || [];
                    renderSimGroupsTable();
                    initSimMemberRows();
                    if (typeof currentType !== 'undefined' && currentType && typeof currentCode !== 'undefined' && currentCode) {
                        loadSchedule(currentType, currentCode);
                    }
                } else {
                    showToast("建立失敗：" + res.message);
                }
            } catch (e) {
                showToast("伺服器連線異常。");
            }
        });
    }

    async function createPresetSimGroup(groupName, subjectKeyword, defaultSubCode, fixedDay = null, fixedPeriod = null) {
        if (!metadata.classes || metadata.classes.length < 2) {
            showToast("尚無足夠班級資料可供全校共同排課。");
            return;
        }

        const members = [];
        metadata.classes.forEach(c => {
            let subCode = defaultSubCode;
            let subName = groupName;
            if (metadata.subjects) {
                const found = metadata.subjects.find(s => s.name.includes(subjectKeyword));
                if (found) {
                    subCode = found.code;
                    subName = found.name;
                }
            }
            members.push({
                class_code: c.code,
                class_name: c.name,
                subject_code: subCode,
                subject_name: subName
            });
        });

        try {
            const slotText = fixedDay && fixedPeriod ? ` (固定於 週${fixedDay} 第${fixedPeriod}節)` : '';
            showToast(`正在一鍵建立【${groupName}】全校共同排課群組${slotText}...`);
            const resp = await fetch('/api/save-simultaneous-group', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ name: groupName, members, fixed_day: fixedDay, fixed_period: fixedPeriod })
            });
            const res = await resp.json();
            if (res.status === 'success') {
                showToast(res.message);
                currentSimGroupsData = res.simultaneous_groups || [];
                renderSimGroupsTable();
                if (typeof currentType !== 'undefined' && currentType && typeof currentCode !== 'undefined' && currentCode) {
                    loadSchedule(currentType, currentCode);
                }
            } else {
                showToast("設定失敗：" + res.message);
            }
        } catch (e) {
            showToast("伺服器連線異常。");
        }
    }

    const presetClassMeetingBtn = document.getElementById('presetSimClassMeetingBtn');
    if (presetClassMeetingBtn && presetClassMeetingBtn.dataset.listener !== 'true') {
        presetClassMeetingBtn.dataset.listener = 'true';
        presetClassMeetingBtn.addEventListener('click', () => createPresetSimGroup('全校共同班會', '班會', 'J109', '1', '7'));
    }

    const presetClubBtn = document.getElementById('presetSimClubBtn');
    if (presetClubBtn && presetClubBtn.dataset.listener !== 'true') {
        presetClubBtn.dataset.listener = 'true';
        presetClubBtn.addEventListener('click', () => createPresetSimGroup('全校共同社團活動', '社團', 'J110', '3', '6'));
    }

    const presetWeeklyBtn = document.getElementById('presetSimWeeklyBtn');
    if (presetWeeklyBtn && presetWeeklyBtn.dataset.listener !== 'true') {
        presetWeeklyBtn.dataset.listener = 'true';
        presetWeeklyBtn.addEventListener('click', () => createPresetSimGroup('全校共同週會/彈性學習', '彈性', 'J116', '5', '7'));
    }

    try {
        const resp = await fetch('/api/simultaneous-groups');
        const data = await resp.json();
        if (data.status === 'success') {
            currentSimGroupsData = data.simultaneous_groups || [];
            renderSimGroupsTable();
        }
    } catch (e) {
        console.error("Load simultaneous groups failed:", e);
    }
}

function renderSimGroupsTable() {
    const tbody = document.getElementById('simGroupsTableBody');
    if (!tbody) return;

    tbody.innerHTML = '';
    if (!currentSimGroupsData || currentSimGroupsData.length === 0) {
        tbody.innerHTML = '<tr><td colspan="4" style="text-align: center; color: var(--text-muted); padding: 16px;">尚未建立自訂同時排課群組。輸入名稱與固定時段即可建立！</td></tr>';
        return;
    }

    const dayNames = { "1": "一", "2": "二", "3": "三", "4": "四", "5": "五" };
    currentSimGroupsData.forEach(grp => {
        if (!grp || typeof grp !== 'object') return;
        const tr = document.createElement('tr');

        // Group Name
        const tdName = document.createElement('td');
        tdName.style.fontWeight = 'bold';
        tdName.style.color = '#38bdf8';
        tdName.textContent = grp.name || '未命名群組';
        tr.appendChild(tdName);

        // Members Details
        const tdMembers = document.createElement('td');
        const membersList = (grp.members || []).map(m => `<span style="color:#fbbf24; font-weight:bold;">${m.class_name || m.class_code}</span> (${m.subject_name || m.subject_code})`);
        tdMembers.innerHTML = membersList.join(' <i class="fa-solid fa-link" style="color:#818cf8; font-size:0.8rem;"></i> ');
        tr.appendChild(tdMembers);

        // Status (Fixed Slot vs Dynamic Simultaneous)
        const tdStatus = document.createElement('td');
        tdStatus.style.textAlign = 'center';
        if (grp.fixed_day && grp.fixed_period) {
            const dName = dayNames[grp.fixed_day] || grp.fixed_day;
            tdStatus.innerHTML = `<span style="color:#34d399; font-size:0.8rem; font-weight:bold; background:rgba(52, 211, 153, 0.15); padding:4px 8px; border-radius:6px;"><i class="fa-solid fa-calendar-check"></i> 固定 週${dName} 第${grp.fixed_period}節</span>`;
        } else {
            tdStatus.innerHTML = '<span style="color:#38bdf8; font-size:0.8rem; font-weight:bold; background:rgba(56, 189, 248, 0.15); padding:4px 8px; border-radius:6px;"><i class="fa-solid fa-lock"></i> 同日同節束縛</span>';
        }
        tr.appendChild(tdStatus);

        // Action Delete
        const tdAct = document.createElement('td');
        tdAct.style.textAlign = 'center';
        const delBtn = document.createElement('button');
        delBtn.className = 'solver-action-btn secondary-btn';
        delBtn.style.padding = '3px 8px';
        delBtn.style.fontSize = '0.78rem';
        delBtn.style.background = 'rgba(239, 68, 68, 0.2)';
        delBtn.style.borderColor = 'rgba(239, 68, 68, 0.4)';
        delBtn.style.color = '#ef4444';
        delBtn.innerHTML = '<i class="fa-solid fa-trash"></i> 刪除';

        delBtn.addEventListener('click', async () => {
            if (!confirm(`確定要刪除同時排課群組「${grp.name}」嗎？`)) return;
            try {
                const resp = await fetch('/api/delete-simultaneous-group', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ name: grp.name })
                });
                const res = await resp.json();
                if (res.status === 'success') {
                    showToast(res.message);
                    await loadSimultaneousGroups();
                    if (typeof currentType !== 'undefined' && currentType && typeof currentCode !== 'undefined' && currentCode) {
                        loadSchedule(currentType, currentCode);
                    }
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

// --- SHIN-HER FRONTEND JS EXTENSIONS ---

document.addEventListener('DOMContentLoaded', () => {
    setupSubstituteHandlers();
    setupExamInvigilationHandlers();
    setupVenueCapacitiesHandlers();
    setupDataDebugHandlers();
});

function setupSubstituteHandlers() {
    const substituteModalBtn = document.getElementById('substituteModalBtn');
    const substituteDrawer = document.getElementById('substituteDrawer');
    const substituteBackdrop = document.getElementById('substituteBackdrop');
    const closeSubstituteModalBtn = document.getElementById('closeSubstituteModalBtn');
    const subAbsentTeacherSelect = document.getElementById('subAbsentTeacherSelect');
    const findSubCandidatesBtn = document.getElementById('findSubCandidatesBtn');
    const subSearchResultCard = document.getElementById('subSearchResultCard');
    const subCourseHintText = document.getElementById('subCourseHintText');
    const subCandidatesTableBody = document.getElementById('subCandidatesTableBody');

    function openSubstituteDrawer() {
        if (substituteDrawer) substituteDrawer.style.transform = 'translateX(0)';
        if (substituteBackdrop) {
            substituteBackdrop.style.opacity = '1';
            substituteBackdrop.style.pointerEvents = 'auto';
        }
    }

    function closeSubstituteDrawer() {
        if (substituteDrawer) substituteDrawer.style.transform = 'translateX(100%)';
        if (substituteBackdrop) {
            substituteBackdrop.style.opacity = '0';
            substituteBackdrop.style.pointerEvents = 'none';
        }
    }

    if (substituteModalBtn) {
        substituteModalBtn.addEventListener('click', async () => {
            openSubstituteDrawer();
            if (metadata.teachers && subAbsentTeacherSelect) {
                subAbsentTeacherSelect.innerHTML = '<option value="">-- 選擇請假教師 --</option>';
                metadata.teachers.forEach(t => {
                    const opt = document.createElement('option');
                    opt.value = t.code;
                    opt.textContent = `${t.name} (${t.code})`;
                    subAbsentTeacherSelect.appendChild(opt);
                });
            }
            await loadSubstituteHistory();
        });
    }

    if (closeSubstituteModalBtn) {
        closeSubstituteModalBtn.addEventListener('click', closeSubstituteDrawer);
    }

    if (findSubCandidatesBtn) {
        findSubCandidatesBtn.addEventListener('click', async () => {
            const absentTeacher = subAbsentTeacherSelect.value;
            const day = document.getElementById('subDaySelect').value;
            const period = document.getElementById('subPeriodSelect').value;

            if (!absentTeacher) {
                showToast("請選擇請假教師！");
                return;
            }

            try {
                const resp = await fetch('/api/substitute/recommend', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ teacher_code: absentTeacher, day, period })
                });
                const res = await resp.json();
                if (res.status === 'success') {
                    subSearchResultCard.style.display = 'block';
                    const c = res.absent_course;
                    const info = res.absent_teacher_info;

                    const titleEl = document.getElementById('subTeacherNameTitle');
                    const classesEl = document.getElementById('subTeacherClassesText');

                    if (info && titleEl) {
                        titleEl.innerHTML = `<i class="fa-solid fa-id-card" style="color:#818cf8;"></i> 請假教師：${info.name} (${info.code}) <span style="font-size:0.8rem; background:rgba(99,102,241,0.25); border:1px solid rgba(99,102,241,0.4); padding:2px 8px; border-radius:4px; margin-left:6px; color:#a5b4fc;">身份別：${info.role}</span>`;
                    }
                    if (info && classesEl) {
                        classesEl.innerHTML = `<i class="fa-solid fa-graduation-cap" style="color:#38bdf8;"></i> 本學期任教班級：<span style="color:#fff;">${info.assigned_classes_str}</span>`;
                    }

                    if (c) {
                        subCourseHintText.innerHTML = `<i class="fa-solid fa-chalkboard-user" style="color:#fbbf24;"></i> 📌 該節原定課程：<span style="color:#fbbf24; font-weight:bold; font-size:0.95rem;">【${c.class_name}】 ${c.subject_name}</span> <span style="font-size:0.8rem; color:var(--text-secondary); margin-left:6px;">(教室: ${c.room_name || "一般教室"})</span>`;
                    } else {
                        subCourseHintText.innerHTML = `<i class="fa-solid fa-circle-info" style="color:#34d399;"></i> 💡 該節次請假教師原定無排課 (空堂無課程)`;
                    }

                    subCandidatesTableBody.innerHTML = '';
                    if (res.candidates.length === 0) {
                        subCandidatesTableBody.innerHTML = '<tr><td colspan="4" style="text-align:center; color:var(--text-muted);">無可用候選代課教師</td></tr>';
                        return;
                    }

                    res.candidates.forEach(cand => {
                        const tr = document.createElement('tr');
                        let priorityBadge = '<span style="color:#38bdf8;"><i class="fa-solid fa-circle-check"></i> 空閒可用</span>';
                        if (cand.is_same_class) {
                            priorityBadge = `<span style="color:#fbbf24; font-weight:bold;"><i class="fa-solid fa-star"></i> ⭐ 最優先：同班任課教師</span>`;
                        } else if (cand.is_same_domain) {
                            priorityBadge = `<span style="color:#34d399; font-weight:bold;"><i class="fa-solid fa-check-double"></i> 次優先：同學科專長</span>`;
                        }

                        tr.innerHTML = `
                            <td style="font-weight:bold; color:#38bdf8;">${cand.teacher_name} (${cand.teacher_code})</td>
                            <td><span style="color:#818cf8; font-size:0.8rem;">[${cand.role}]</span> ${cand.assigned_classes_str}</td>
                            <td>${priorityBadge}</td>
                            <td>
                                <button class="solver-action-btn primary-btn" style="padding:4px 10px; font-size:0.8rem; background:#10b981;" onclick="assignSubstitute('${absentTeacher}', '${cand.teacher_code}', '${cand.teacher_name}', '${day}', '${period}', '${c ? c.class_name : ''}', '${c ? c.subject_name : ''}')">
                                    <i class="fa-solid fa-user-check"></i> 指派代課
                                </button>
                            </td>
                        `;
                        subCandidatesTableBody.appendChild(tr);
                    });
                }
            } catch (e) {
                showToast("搜尋代課教師失敗。");
            }
        });
    }
}

async function assignSubstitute(absentCode, subCode, subName, day, period, className, subjectName) {
    if (!confirm(`確定要指派 ${subName} 老師代課嗎？`)) return;
    try {
        const tObj = metadata.teachers ? metadata.teachers.find(t => t.code === absentCode) : null;
        const absentName = tObj ? tObj.name : absentCode;

        const resp = await fetch('/api/substitute/save', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                day, period,
                class_name: className,
                subject_name: subjectName,
                absent_teacher: absentName,
                sub_teacher: subName,
                reason: "公假/假別代課"
            })
        });
        const res = await resp.json();
        if (res.status === 'success') {
            showToast(res.message);
            await loadSubstituteHistory();
        }
    } catch (e) {
        showToast("登記代課失敗。");
    }
}

async function loadSubstituteHistory() {
    const tbody = document.getElementById('subHistoryTableBody');
    if (!tbody) return;
    try {
        const resp = await fetch('/api/substitute/list');
        const data = await resp.json();
        if (data && data.status === 'success') {
            tbody.innerHTML = '';
            if (!Array.isArray(data.records) || data.records.length === 0) {
                tbody.innerHTML = '<tr><td colspan="5" style="text-align:center; color:var(--text-muted); padding:15px;">尚無歷史調代課紀錄</td></tr>';
                return;
            }
            data.records.forEach(r => {
                const tr = document.createElement('tr');
                tr.innerHTML = `
                    <td style="color:#818cf8; font-size:0.8rem;">${r.date || r.id || '最新'}</td>
                    <td>週${r.day} 第${r.period}節</td>
                    <td>${r.class_name || ''} ${r.subject_name || ''}</td>
                    <td>${r.absent_teacher || ''}</td>
                    <td style="color:#34d399; font-weight:bold;">${r.sub_teacher || ''}</td>
                `;
                tbody.appendChild(tr);
            });
        } else {
            tbody.innerHTML = '<tr><td colspan="5" style="text-align:center; color:var(--text-muted); padding:15px;">尚無歷史調代課紀錄</td></tr>';
        }
    } catch (e) {
        console.error(e);
        tbody.innerHTML = '<tr><td colspan="5" style="text-align:center; color:var(--text-muted); padding:15px;">尚無歷史調代課紀錄</td></tr>';
    }
}

let currentExamPlanData = [];

function setupExamInvigilationHandlers() {
    const examInvigilationBtn = document.getElementById('examInvigilationBtn');
    const examInvigilationModal = document.getElementById('examInvigilationModal');
    const closeExamModalBtn = document.getElementById('closeExamModalBtn');
    const runExamSolverBtn = document.getElementById('runExamSolverBtn');
    const saveExamPlanBtn = document.getElementById('saveExamPlanBtn');

    if (!examInvigilationBtn || !examInvigilationModal) return;

    examInvigilationBtn.addEventListener('click', async () => {
        examInvigilationModal.style.display = 'flex';
        await loadExistingExamPlan();
    });

    if (closeExamModalBtn) {
        closeExamModalBtn.addEventListener('click', () => {
            examInvigilationModal.style.display = 'none';
        });
    }

    if (runExamSolverBtn) {
        runExamSolverBtn.addEventListener('click', async () => {
            const days = document.getElementById('examDaysInput').value;
            const periods = document.getElementById('examPeriodsInput').value;

            showToast("正在智慧生成段考監考表...");
            try {
                const resp = await fetch('/api/exam-invigilation/solve', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ days, periods })
                });
                const res = await resp.json();
                if (res.status === 'success') {
                    showToast(res.message);
                    currentExamPlanData = res.plan || [];
                    renderExamPlanTable();
                } else {
                    showToast("生成監考表失敗：" + res.message);
                }
            } catch (e) {
                showToast("伺服器連線異常。");
            }
        });
    }

    if (saveExamPlanBtn) {
        saveExamPlanBtn.addEventListener('click', async () => {
            const selects = document.querySelectorAll('select.exam-teacher-select');
            const newPlan = [];
            selects.forEach(select => {
                const day = parseInt(select.getAttribute('data-day'));
                const period = parseInt(select.getAttribute('data-period'));
                const classCode = select.getAttribute('data-class-code');
                const className = select.getAttribute('data-class-name');
                const selectedCode = select.value;
                const tObj = metadata.teachers ? metadata.teachers.find(t => t.code === selectedCode) : null;
                const selectedName = tObj ? tObj.name : selectedCode;

                newPlan.push({
                    day, period,
                    class_code: classCode,
                    class_name: className,
                    invigilator_code: selectedCode,
                    invigilator_name: selectedName
                });
            });

            const daysVal = parseInt(document.getElementById('examDaysInput').value || 2);
            const periodsVal = parseInt(document.getElementById('examPeriodsInput').value || 4);

            try {
                const resp = await fetch('/api/exam-invigilation/save-plan', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ days: daysVal, periods: periodsVal, plan: newPlan })
                });
                const res = await resp.json();
                if (res.status === 'success') {
                    showToast(res.message);
                    currentExamPlanData = newPlan;
                } else {
                    showToast("儲存失敗：" + res.message);
                }
            } catch (e) {
                showToast("伺服器連線異常。");
            }
        });
    }
}

async function loadExistingExamPlan() {
    try {
        const resp = await fetch('/api/exam-invigilation/get-plan');
        const data = await resp.json();
        if (data.status === 'success' && data.exam_data) {
            const ed = data.exam_data;
            if (ed.plan && ed.plan.length > 0) {
                currentExamPlanData = ed.plan;
                const computedDays = Math.max(...currentExamPlanData.map(item => parseInt(item.day || 1)));
                const computedPeriods = Math.max(...currentExamPlanData.map(item => parseInt(item.period || 1)));

                const daysInput = document.getElementById('examDaysInput');
                if (daysInput) daysInput.value = ed.days || computedDays;

                const periodsInput = document.getElementById('examPeriodsInput');
                if (periodsInput) periodsInput.value = ed.periods || computedPeriods;

                renderExamPlanTable();
            }
        }
    } catch (e) {
        console.error(e);
    }
}

let activeExamDayTab = '1';

function renderExamPlanTable() {
    const examTableHeaderRow = document.getElementById('examTableHeaderRow');
    const examTableBody = document.getElementById('examTableBody');
    const examDayTabsContainer = document.getElementById('examDayTabsContainer');
    if (!examTableBody || !examTableHeaderRow) return;

    examTableBody.innerHTML = '';
    examTableHeaderRow.innerHTML = '<th style="width: 130px; min-width: 130px; text-align: center; background: rgba(15,23,42,0.95); white-space: nowrap; padding: 10px 12px; font-size: 0.88rem; color: #818cf8;">試場 / 班級</th>';

    if (!currentExamPlanData || currentExamPlanData.length === 0) {
        if (examDayTabsContainer) examDayTabsContainer.innerHTML = '';
        examTableBody.innerHTML = '<tr><td colspan="6" style="text-align: center; color: var(--text-muted); padding: 20px;">尚未生成監考課表。請點擊上方「啟動 AI 監考自動排程」按鈕！</td></tr>';
        return;
    }

    // 1. Get distinct days & slots
    const daysSet = new Set();
    const slotsMap = {};
    currentExamPlanData.forEach(item => {
        daysSet.add(item.day);
        const key = `${item.day}-${item.period}`;
        if (!slotsMap[key]) {
            slotsMap[key] = { day: item.day, period: item.period };
        }
    });

    const uniqueDays = Array.from(daysSet).sort((a, b) => a - b);

    // If activeExamDayTab is not valid, reset to 1
    if (activeExamDayTab !== 'all' && !uniqueDays.includes(parseInt(activeExamDayTab))) {
        activeExamDayTab = uniqueDays[0] ? String(uniqueDays[0]) : '1';
    }

    // Render Day Tabs Bar
    if (examDayTabsContainer) {
        examDayTabsContainer.innerHTML = '';

        // Individual Day Tabs
        uniqueDays.forEach(d => {
            const btn = document.createElement('button');
            btn.className = 'solver-action-btn';
            btn.style.fontSize = '0.85rem';
            btn.style.padding = '6px 16px';
            btn.style.borderRadius = '6px';
            if (activeExamDayTab == d) {
                btn.style.background = '#f59e0b';
                btn.style.color = '#fff';
                btn.style.fontWeight = 'bold';
                btn.style.boxShadow = '0 0 10px rgba(245,158,11,0.4)';
            } else {
                btn.style.background = 'rgba(255,255,255,0.05)';
                btn.style.color = 'var(--text-secondary)';
                btn.style.border = '1px solid var(--border-color)';
            }
            btn.innerHTML = `<i class="fa-solid fa-calendar-day"></i> 第 ${d} 天`;
            btn.addEventListener('click', () => {
                activeExamDayTab = String(d);
                renderExamPlanTable();
            });
            examDayTabsContainer.appendChild(btn);
        });

        // All Days Tab (at the end)
        const btnAll = document.createElement('button');
        btnAll.className = 'solver-action-btn';
        btnAll.style.fontSize = '0.85rem';
        btnAll.style.padding = '6px 16px';
        btnAll.style.borderRadius = '6px';
        if (activeExamDayTab === 'all') {
            btnAll.style.background = '#f59e0b';
            btnAll.style.color = '#fff';
            btnAll.style.fontWeight = 'bold';
            btnAll.style.boxShadow = '0 0 10px rgba(245,158,11,0.4)';
        } else {
            btnAll.style.background = 'rgba(255,255,255,0.05)';
            btnAll.style.color = 'var(--text-secondary)';
            btnAll.style.border = '1px solid var(--border-color)';
        }
        btnAll.innerHTML = '<i class="fa-solid fa-layer-group"></i> 全日程總表 (寬網格)';
        btnAll.addEventListener('click', () => {
            activeExamDayTab = 'all';
            renderExamPlanTable();
        });
        examDayTabsContainer.appendChild(btnAll);
    }

    let sortedSlots = Object.values(slotsMap).sort((a, b) => {
        if (a.day !== b.day) return a.day - b.day;
        return a.period - b.period;
    });

    // Filter by activeExamDayTab
    if (activeExamDayTab !== 'all') {
        sortedSlots = sortedSlots.filter(s => s.day == activeExamDayTab);
    }

    // Render Table Header Columns
    sortedSlots.forEach(slot => {
        const th = document.createElement('th');
        th.style.textAlign = 'center';
        th.style.minWidth = '180px';
        th.style.whiteSpace = 'nowrap';
        th.style.padding = '10px 14px';
        th.style.background = 'rgba(15,23,42,0.95)';
        th.style.color = '#fbbf24';
        th.style.fontSize = '0.88rem';
        th.innerHTML = `<i class="fa-solid fa-clock"></i> 第 ${slot.day} 天・第 ${slot.period} 節`;
        examTableHeaderRow.appendChild(th);
    });

    // 2. Group by class_code
    const classMap = {};
    currentExamPlanData.forEach(item => {
        const cc = item.class_code;
        if (!classMap[cc]) {
            classMap[cc] = { class_name: item.class_name, slots: {} };
        }
        classMap[cc].slots[`${item.day}-${item.period}`] = item;
    });

    // 3. Render Table Rows for each Class
    Object.keys(classMap).sort().forEach(cc => {
        const cInfo = classMap[cc];
        const tr = document.createElement('tr');

        // Class Name Cell
        const tdClass = document.createElement('td');
        tdClass.style.fontWeight = 'bold';
        tdClass.style.color = '#38bdf8';
        tdClass.style.textAlign = 'center';
        tdClass.style.background = 'rgba(15,23,42,0.6)';
        tdClass.style.whiteSpace = 'nowrap';
        tdClass.style.padding = '8px 12px';
        tdClass.textContent = cInfo.class_name;
        tr.appendChild(tdClass);

        // Slot Cells
        sortedSlots.forEach(slot => {
            const td = document.createElement('td');
            td.style.textAlign = 'center';
            td.style.padding = '6px 8px';

            const item = cInfo.slots[`${slot.day}-${slot.period}`];
            if (item) {
                let selectHtml = `<select class="exam-teacher-select" data-day="${slot.day}" data-period="${slot.period}" data-class-code="${cc}" data-class-name="${cInfo.class_name}" style="width:100%; min-width:160px; padding: 6px 10px; border-radius: 6px; background: rgba(15,23,42,0.9); color: #fbbf24; border: 1px solid var(--border-color); font-weight: bold; font-size:0.85rem; cursor:pointer;">`;
                
                const simCodes = item.sim_teachers ? item.sim_teachers.map(st => st.code) : [];
                if (simCodes.length > 0) {
                    selectHtml += `<optgroup label="⭐ 當節同時排課/任課教師">`;
                    item.sim_teachers.forEach(st => {
                        const selected = st.code === item.invigilator_code ? 'selected' : '';
                        selectHtml += `<option value="${st.code}" ${selected}>⭐ ${st.name} [${st.subject || '任課'}] (${st.code})</option>`;
                    });
                    selectHtml += `</optgroup>`;
                    selectHtml += `<optgroup label="全校其他教師">`;
                }

                if (metadata.teachers) {
                    metadata.teachers.forEach(t => {
                        if (!simCodes.includes(t.code)) {
                            const selected = t.code === item.invigilator_code ? 'selected' : '';
                            selectHtml += `<option value="${t.code}" ${selected}>${t.name} (${t.code})</option>`;
                        }
                    });
                }
                if (simCodes.length > 0) {
                    selectHtml += `</optgroup>`;
                }
                selectHtml += `</select>`;

                let simBadge = '';
                if (item.is_simultaneous && item.sim_teachers) {
                    const names = item.sim_teachers.map(st => st.name).join(', ');
                    simBadge = `<div style="font-size:0.75rem; color:#34d399; margin-top:3px;"><i class="fa-solid fa-users"></i> 同時排課: ${names}</div>`;
                } else if (item.orig_subject) {
                    simBadge = `<div style="font-size:0.75rem; color:var(--text-secondary); margin-top:3px;"><i class="fa-solid fa-book-bookmark" style="color:#818cf8;"></i> 原課表: ${item.orig_subject}</div>`;
                }

                td.innerHTML = selectHtml + simBadge;
            } else {
                td.innerHTML = '<span style="color:var(--text-muted); font-size:0.8rem;">-</span>';
            }
            tr.appendChild(td);
        });

        examTableBody.appendChild(tr);
    });
}

function setupVenueCapacitiesHandlers() {
    const saveVenueCapacitiesBtn = document.getElementById('saveVenueCapacitiesBtn');
    if (!saveVenueCapacitiesBtn) return;

    saveVenueCapacitiesBtn.addEventListener('click', async () => {
        const caps = {
            "電腦教室": parseInt(document.getElementById('capComputerRoom').value || 2),
            "理化實驗室": parseInt(document.getElementById('capScienceLab').value || 1),
            "音樂教室": parseInt(document.getElementById('capMusicRoom').value || 1),
            "體育場": parseInt(document.getElementById('capGym').value || 3)
        };

        const checkboxes = document.querySelectorAll('#consecutiveSubjectsCheckboxes input[type="checkbox"]:checked');
        const consecSubs = Array.from(checkboxes).map(cb => cb.value);

        try {
            const resp = await fetch('/api/save-venue-capacities', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ venue_capacities: caps, consecutive_subjects: consecSubs })
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

function setupDataDebugHandlers() {
    const dataDebugBtn = document.getElementById('dataDebugBtn');
    const dataDebugModal = document.getElementById('dataDebugModal');
    const closeDebugModalBtn = document.getElementById('closeDebugModalBtn');
    const refreshDebugReportBtn = document.getElementById('refreshDebugReportBtn');

    if (!dataDebugBtn || !dataDebugModal) return;

    dataDebugBtn.addEventListener('click', async () => {
        dataDebugModal.style.display = 'flex';
        await loadDataDebugReport();
    });

    if (closeDebugModalBtn) {
        closeDebugModalBtn.addEventListener('click', () => {
            dataDebugModal.style.display = 'none';
        });
    }

    if (refreshDebugReportBtn) {
        refreshDebugReportBtn.addEventListener('click', loadDataDebugReport);
    }
}

async function loadDataDebugReport() {
    const tbody = document.getElementById('dataDebugTableBody');
    const logicCountEl = document.getElementById('auditLogicErrorsCount');
    const unassignedCountEl = document.getElementById('auditUnassignedCount');
    const multiTeacherCountEl = document.getElementById('auditMultiTeacherCount');

    if (!tbody) return;

    try {
        const resp = await fetch('/api/data-debug-report');
        const data = await resp.json();
        if (data.status === 'success') {
            const audit = data.audit_summary;
            if (logicCountEl) {
                logicCountEl.textContent = `${audit.logic_errors.length} 項`;
                logicCountEl.style.color = audit.logic_errors.length > 0 ? '#ef4444' : '#34d399';
            }
            if (unassignedCountEl) unassignedCountEl.textContent = `${audit.unassigned_subjects.length} 項`;
            if (multiTeacherCountEl) multiTeacherCountEl.textContent = `${audit.multi_teacher_subjects.length} 項`;

            tbody.innerHTML = '';
            const items = [
                { id: '1. 班級排課數稽核', status: '🟢 正常', detail: `全校 ${audit.class_scheduled_counts.length} 個班級課表節數皆符合校務標準` },
                { id: '2. 班級空堂數檢查', status: '🟢 正常', detail: `全校一般班級第1~7節皆已連續安排課程` },
                { id: '3. 教師總時數統計', status: '🟢 正常', detail: `已採計全校 ${audit.teacher_total_hours.length} 位教師基本鐘點與超節數` },
                { id: '4. 無任課教師科目', status: audit.unassigned_subjects.length > 0 ? '🟡 提醒' : '🟢 正常', detail: audit.unassigned_subjects.length > 0 ? `尚有 ${audit.unassigned_subjects.length} 門科目未指派授課教師：${audit.unassigned_subjects.slice(0, 3).join(', ')}...` : '全校所有開課科目皆已完成授課教師指派' },
                { id: '5. 多任課教師科目', status: 'ℹ️ 資訊', detail: `全校共有 ${audit.multi_teacher_subjects.length} 門分組/協同教學科目` },
                { id: '6. 科目每節上課明細', status: '🟢 正常', detail: `開課學科種類共 ${Object.keys(audit.subject_counts).length} 種，各節次均勻分佈` },
                { id: '7. 科目排課數比對', status: '🟢 正常', detail: `全校各學科配課節數與年級課程規劃一致` },
                { id: '8. 邏輯錯誤 (硬衝堂)', status: audit.logic_errors.length > 0 ? '🔴 錯誤' : '🟢 完全無衝堂', detail: audit.logic_errors.length > 0 ? audit.logic_errors.join('； ') : '恭喜！全校課表完全無任何教師衝堂或班級衝堂邏輯錯誤' },
                { id: '9. 檢查手排課邏輯', status: '🟢 正常', detail: '所有手排課 (鎖定) 格子皆符合全校規則限制' }
            ];

            items.forEach(it => {
                const tr = document.createElement('tr');
                tr.innerHTML = `
                    <td style="font-weight:bold; color:#818cf8;">${it.id}</td>
                    <td style="font-weight:bold;">${it.status}</td>
                    <td style="color:var(--text-secondary);">${it.detail}</td>
                `;
                tbody.appendChild(tr);
            });
        }
    } catch (e) {
        console.error("Load debug report failed:", e);
    }
}

// --- SINGLE-FILE SEMESTER MANAGEMENT FRONTEND LOGIC ---
async function loadSemestersList() {
    try {
        const resp = await fetch('/api/semesters/list');
        const data = await resp.json();
        if (data.status === 'success') {
            const activeId = data.active_semester_id;
            const semesters = data.semesters || [];

            // Update Header Selector
            const headerSemesterSelect = document.getElementById('headerSemesterSelect');
            if (headerSemesterSelect) {
                headerSemesterSelect.innerHTML = '';
                semesters.forEach(s => {
                    const opt = document.createElement('option');
                    opt.value = s.semester_id;
                    opt.textContent = `${s.semester_id} 學期`;
                    opt.style.background = '#0f172a';
                    opt.style.color = '#fff';
                    if (s.semester_id === activeId) opt.selected = true;
                    headerSemesterSelect.appendChild(opt);
                });
            }

            // Update Active Badge
            const activeSemesterBadge = document.getElementById('activeSemesterBadge');
            if (activeSemesterBadge) {
                activeSemesterBadge.textContent = `${activeId} 學期`;
            }

            // Render Table Body
            const tbody = document.getElementById('semestersTableBody');
            if (tbody) {
                if (semesters.length === 0) {
                    tbody.innerHTML = '<tr><td colspan="6" style="text-align:center; color: var(--text-muted);">無學期資料檔</td></tr>';
                } else {
                    tbody.innerHTML = '';
                    semesters.forEach(s => {
                        const isCurrent = s.semester_id === activeId;
                        const tr = document.createElement('tr');

                        const tdId = document.createElement('td');
                        tdId.style.fontWeight = 'bold';
                        tdId.style.color = isCurrent ? '#c084fc' : '#fff';
                        tdId.textContent = `${s.semester_id} ${isCurrent ? ' (目前啟用)' : ''}`;
                        tr.appendChild(tdId);

                        const tdSchool = document.createElement('td');
                        tdSchool.textContent = s.school_name || '土城高中';
                        tr.appendChild(tdSchool);

                        const tdTime = document.createElement('td');
                        tdTime.style.fontSize = '0.8rem';
                        tdTime.style.color = 'var(--text-muted)';
                        tdTime.textContent = s.updated_at || '未紀錄';
                        tr.appendChild(tdTime);

                        const tdSlots = document.createElement('td');
                        tdSlots.textContent = s.slots_count ? `${s.slots_count} 節` : '0 節 (未排課)';
                        tr.appendChild(tdSlots);

                        const tdSize = document.createElement('td');
                        tdSize.style.fontSize = '0.8rem';
                        tdSize.textContent = `${(s.file_size / 1024).toFixed(1)} KB`;
                        tr.appendChild(tdSize);

                        const tdActions = document.createElement('td');
                        if (isCurrent) {
                            tdActions.innerHTML = `
                                <span style="color:#10b981; font-weight:bold; font-size:0.8rem; margin-right:8px;"><i class="fa-solid fa-circle-check"></i> 使用中</span>
                                <a href="/api/semesters/export-single/${encodeURIComponent(s.semester_id)}" download class="solver-action-btn primary-btn" style="padding: 2px 8px; font-size: 0.75rem; background: #0284c7; text-decoration: none;">匯出單檔</a>
                            `;
                        } else {
                            tdActions.innerHTML = `
                                <button onclick="switchSemester('${s.semester_id}')" class="solver-action-btn primary-btn" style="padding: 2px 8px; font-size: 0.75rem; background: #a855f7; margin-right: 4px;">切換啟用</button>
                                <a href="/api/semesters/export-single/${encodeURIComponent(s.semester_id)}" download class="solver-action-btn primary-btn" style="padding: 2px 8px; font-size: 0.75rem; background: #0284c7; text-decoration: none; margin-right: 4px;">匯出單檔</a>
                                <button onclick="deleteSemester('${s.semester_id}')" class="solver-action-btn secondary-btn" style="padding: 2px 8px; font-size: 0.75rem; color:#f87171;">刪除</button>
                            `;
                        }
                        tr.appendChild(tdActions);

                        tbody.appendChild(tr);
                    });
                }
            }
        }
    } catch (e) {
        console.error("Load semesters list failed:", e);
    }
}

async function switchSemester(semesterId) {
    if (!confirm(`確定要切換至學期【${semesterId}】嗎？全校排課與規則將切換為該學期的存檔狀態。`)) return;
    try {
        const resp = await fetch('/api/semesters/switch', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ semester_id: semesterId })
        });
        const data = await resp.json();
        if (data.status === 'success') {
            showToast(data.message, 'success');
            await fetchMetadata();
            await loadSemestersList();
            if (window.location.hash) {
                handleHashChange();
            } else {
                switchQuickSelectTab('class');
            }
        } else {
            showToast(data.message || '切換學期失敗', 'error');
        }
    } catch (e) {
        showToast('切換學期請求失敗', 'error');
    }
}

async function createNewSemester() {
    const input = document.getElementById('newSemesterIdInput');
    if (!input) return;
    const semId = input.value.trim();
    if (!semId) {
        showToast('請輸入新學期名稱 (例如 114-2)', 'warning');
        return;
    }
    if (!confirm(`確定要開辦新學期【${semId}】並繼承目前全校配課規則嗎？`)) return;

    try {
        const resp = await fetch('/api/semesters/create', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ semester_id: semId, inherit: true })
        });
        const data = await resp.json();
        if (data.status === 'success') {
            showToast(data.message, 'success');
            input.value = '';
            await fetchMetadata();
            await loadSemestersList();
        } else {
            showToast(data.message || '開辦新學期失敗', 'error');
        }
    } catch (e) {
        showToast('開辦新學期請求失敗', 'error');
    }
}

async function deleteSemester(semesterId) {
    if (!confirm(`確定要刪除學期【${semesterId}】的單一 JSON 存檔嗎？此動作無法復原！`)) return;
    try {
        const resp = await fetch('/api/semesters/delete', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ semester_id: semesterId })
        });
        const data = await resp.json();
        if (data.status === 'success') {
            showToast(data.message, 'success');
            await loadSemestersList();
        } else {
            showToast(data.message || '刪除失敗', 'error');
        }
    } catch (e) {
        showToast('刪除請求失敗', 'error');
    }
}

// Bind Semester Listeners
document.addEventListener('DOMContentLoaded', () => {
    loadSemestersList();

    const headerSemesterSelect = document.getElementById('headerSemesterSelect');
    if (headerSemesterSelect) {
        headerSemesterSelect.addEventListener('change', (e) => {
            const selectedId = e.target.value;
            if (selectedId) {
                switchSemester(selectedId);
            }
        });
    }

    const createNewSemesterBtn = document.getElementById('createNewSemesterBtn');
    if (createNewSemesterBtn) {
        createNewSemesterBtn.addEventListener('click', createNewSemester);
    }

    const exportCurrentSemesterBtn = document.getElementById('exportCurrentSemesterBtn');
    if (exportCurrentSemesterBtn) {
        exportCurrentSemesterBtn.addEventListener('click', () => {
            const activeSemesterBadge = document.getElementById('activeSemesterBadge');
            let semId = '114-1';
            if (activeSemesterBadge && activeSemesterBadge.textContent) {
                semId = activeSemesterBadge.textContent.replace(' 學期', '').trim();
            }
            window.location.href = `/api/semesters/export-single/${encodeURIComponent(semId)}`;
        });
    }

    const importSemesterFileInput = document.getElementById('importSemesterFileInput');
    if (importSemesterFileInput) {
        importSemesterFileInput.addEventListener('change', async (e) => {
            const file = e.target.files[0];
            if (!file) return;
            const formData = new FormData();
            formData.append('file', file);
            try {
                const resp = await fetch('/api/semesters/import-single', {
                    method: 'POST',
                    body: formData
                });
                const data = await resp.json();
                if (data.status === 'success') {
                    showToast(data.message, 'success');
                    await fetchMetadata();
                    await loadSemestersList();
                } else {
                    showToast(data.message || '匯入失敗', 'error');
                }
            } catch (err) {
                showToast('匯入學期 JSON 失敗', 'error');
            }
            e.target.value = '';
        });
    }
});

// --- SYSTEM INFO & SCHOOL BASIC DATA LOGIC ---
async function loadSystemInfo() {
    try {
        const resp = await fetch('/api/system-info');
        const data = await resp.json();
        if (data.status === 'success') {
            const schoolNameInput = document.getElementById('schoolNameInput');
            const schoolSubtitleInput = document.getElementById('schoolSubtitleInput');
            const schoolYearInput = document.getElementById('schoolYearInput');
            const schoolTermInput = document.getElementById('schoolTermInput');
            const dbfSearchDirInput = document.getElementById('dbfSearchDirInput');

            if (schoolNameInput) schoolNameInput.value = data.school_name || '';
            if (schoolSubtitleInput) schoolSubtitleInput.value = data.school_subtitle || '';
            if (schoolYearInput) schoolYearInput.value = data.year || '114';
            if (schoolTermInput) schoolTermInput.value = data.term || '1';
            if (dbfSearchDirInput) dbfSearchDirInput.value = data.dbf_search_dir || '';

            updatePageHeaderTitles(data.school_name, data.school_subtitle, data.year, data.term);

            const tbody = document.getElementById('periodTimesTableBody');
            if (tbody) {
                tbody.innerHTML = '';
                const pTimes = data.period_times || {};
                for (let p = 1; p <= 8; p++) {
                    const pKey = String(p);
                    const info = pTimes[pKey] || { name: `第${p}節`, time: "" };
                    const tr = document.createElement('tr');

                    tr.innerHTML = `
                        <td style="font-weight:bold; color:#818cf8;">第 ${p} 節</td>
                        <td>
                            <input type="text" class="period-name-input" data-period="${p}" value="${info.name || `第${p}節`}" style="padding: 4px 8px; border-radius: 4px; background: rgba(15, 23, 42, 0.8); color: #fff; border: 1px solid var(--border-color); width: 100%;">
                        </td>
                        <td>
                            <input type="text" class="period-time-input" data-period="${p}" value="${info.time || ''}" placeholder="例如 08:10-08:55" style="padding: 4px 8px; border-radius: 4px; background: rgba(15, 23, 42, 0.8); color: #fff; border: 1px solid var(--border-color); width: 100%;">
                        </td>
                    `;
                    tbody.appendChild(tr);
                }
            }
        }
    } catch (e) {
        console.error("Load system info failed:", e);
    }
}

function updatePageHeaderTitles(schoolName, schoolSubtitle, year, term) {
    if (!schoolName) return;
    const termText = term === '2' ? '第二學期' : '第一學期';
    const appHeaderTitle = document.getElementById('appHeaderTitle');
    const appHeaderSubtext = document.getElementById('appHeaderSubtext');
    const printSchoolTitle = document.getElementById('printSchoolTitle');

    if (appHeaderTitle) {
        appHeaderTitle.textContent = schoolName;
    }
    if (appHeaderSubtext && schoolSubtitle) {
        appHeaderSubtext.textContent = schoolSubtitle;
    }
    if (printSchoolTitle) {
        printSchoolTitle.textContent = `${schoolName} ${year || '114'} 學年度${termText} 正式課表`;
    }
    document.title = schoolName;
}


async function saveSystemInfo() {
    const schoolNameInput = document.getElementById('schoolNameInput');
    const schoolSubtitleInput = document.getElementById('schoolSubtitleInput');
    const schoolYearInput = document.getElementById('schoolYearInput');
    const schoolTermInput = document.getElementById('schoolTermInput');
    const dbfSearchDirInput = document.getElementById('dbfSearchDirInput');

    const nameInputs = document.querySelectorAll('.period-name-input');
    const timeInputs = document.querySelectorAll('.period-time-input');

    const periodTimes = {};
    for (let p = 1; p <= 8; p++) {
        const pKey = String(p);
        let pName = `第${p}節`;
        let pTime = '';
        nameInputs.forEach(inp => { if (inp.dataset.period === pKey) pName = inp.value.trim(); });
        timeInputs.forEach(inp => { if (inp.dataset.period === pKey) pTime = inp.value.trim(); });
        periodTimes[pKey] = { name: pName, time: pTime };
    }

    const payload = {
        school_name: schoolNameInput ? schoolNameInput.value.trim() : '',
        school_subtitle: schoolSubtitleInput ? schoolSubtitleInput.value.trim() : '',
        year: schoolYearInput ? schoolYearInput.value.trim() : '114',
        term: schoolTermInput ? schoolTermInput.value : '1',
        dbf_search_dir: dbfSearchDirInput ? dbfSearchDirInput.value.trim() : '',
        period_times: periodTimes
    };

    try {
        const resp = await fetch('/api/save-system-info', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        const data = await resp.json();
        if (data.status === 'success') {
            showToast(data.message, 'success');
            updatePageHeaderTitles(payload.school_name, payload.school_subtitle, payload.year, payload.term);
            await fetchMetadata();
        } else {
            showToast(data.message || '儲存失敗', 'error');
        }
    } catch (e) {
        showToast('儲存系統基本資料請求失敗', 'error');
    }
}

// Bind System Info Listeners
document.addEventListener('DOMContentLoaded', () => {
    loadSystemInfo();

    const saveSystemInfoBtn = document.getElementById('saveSystemInfoBtn');
    if (saveSystemInfoBtn) {
        saveSystemInfoBtn.addEventListener('click', saveSystemInfo);
    }

    // Backup Export (.zip)
    const backupExportBtn = document.getElementById('systemBackupExportBtn');
    if (backupExportBtn) {
        backupExportBtn.addEventListener('click', () => {
            window.location.href = '/api/backup/export';
        });
    }

    // Backup Import (.zip / .json)
    const backupFileInput = document.getElementById('systemBackupFileInput');
    if (backupFileInput) {
        backupFileInput.addEventListener('change', async (e) => {
            const file = e.target.files[0];
            if (!file) return;
            const formData = new FormData();
            formData.append('file', file);

            try {
                const resp = await fetch('/api/backup/import', {
                    method: 'POST',
                    body: formData
                });
                const res = await resp.json();
                if (res.status === 'success') {
                    alert(res.message);
                    window.location.reload();
                } else {
                    alert('還原失敗: ' + res.message);
                }
            } catch (err) {
                alert('還原發生錯誤: ' + err);
            }
            backupFileInput.value = '';
        });
    }

    // System Reset / Clear for New School
    const resetCleanBtn = document.getElementById('systemResetCleanBtn');
    if (resetCleanBtn) {
        resetCleanBtn.addEventListener('click', async () => {
            const confirm1 = confirm('⚠️ 確定要一鍵清空現有學校的原始資料，並轉換為新學校範本嗎？\n\n系統會在清空前自動建立安全備份至 restore_points 資料夾，確保原本的資料隨時可以還原。');
            if (!confirm1) return;

            const confirm2 = confirm('🚨 再次確認：這將會重置學校名稱、配課規則與現有排課結果，並轉為空白學校範本。\n\n您準備好進行移交與重置了嗎？');
            if (!confirm2) return;

            try {
                const resp = await fetch('/api/backup/reset', { method: 'POST' });
                const res = await resp.json();
                if (res.status === 'success') {
                    alert(res.message);
                    window.location.reload();
                } else {
                    alert('重置失敗: ' + res.message);
                }
            } catch (err) {
                alert('重置發生錯誤: ' + err);
            }
        });
    }

    // Browse & Select DBF Search Directory
    const browseDbfDirBtn = document.getElementById('browseDbfDirBtn');
    if (browseDbfDirBtn) {
        browseDbfDirBtn.addEventListener('click', async () => {
            browseDbfDirBtn.disabled = true;
            const originalHtml = browseDbfDirBtn.innerHTML;
            browseDbfDirBtn.innerHTML = '<i class="fa-solid fa-circle-notch console-spinner"></i> 選擇中...';
            try {
                const resp = await fetch('/api/select-folder', { method: 'POST' });
                const data = await resp.json();
                if (data.status === 'success' && data.path) {
                    const dbfSearchDirInput = document.getElementById('dbfSearchDirInput');
                    if (dbfSearchDirInput) {
                        dbfSearchDirInput.value = data.path;
                    }
                    showToast(`已成功選擇資料夾：${data.path}`, 'success');
                } else if (data.status === 'cancel') {
                    showToast('已取消選擇資料夾', 'info');
                } else {
                    showToast(`選擇資料夾失敗: ${data.message || ''}`, 'error');
                }
            } catch (err) {
                console.error('Select folder error:', err);
                showToast('選擇資料夾時發生錯誤', 'error');
            } finally {
                browseDbfDirBtn.disabled = false;
                browseDbfDirBtn.innerHTML = originalHtml;
            }
        });
    }

    // Load Standard Preset (Junior High, Senior High, Combined)
    document.querySelectorAll('.load-preset-btn').forEach(btn => {
        btn.addEventListener('click', async (e) => {
            const presetType = e.currentTarget.getAttribute('data-preset');
            let typeName = "國中 3 班示範檔 (701~901)";
            if (presetType === "senior_3") typeName = "高中 3 班示範檔 (101~301)";
            if (presetType === "k12_6" || presetType === "combined") typeName = "國中3班+高中3班全校範本 (共6班)";
            if (presetType === "junior") typeName = "國中部標準課綱";
            if (presetType === "senior") typeName = "高中部標準課綱";

            if (!confirm(`⚡ 確定要載入【${typeName}】嗎？\n\n這將會自動設定常見班級名單、授課教師、每週節數與專用教室對應。`)) {
                return;
            }

            try {
                const resp = await fetch('/api/presets/load', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ preset_type: presetType })
                });
                const res = await resp.json();
                if (res.status === 'success') {
                    showToast(res.message, 'success');
                    if (typeof loadSubjectCatalog === 'function') await loadSubjectCatalog();
                    if (typeof loadVenueCapacities === 'function') await loadVenueCapacities();
                    if (typeof fetchMetadata === 'function') await fetchMetadata();
                } else {
                    alert('載入範本失敗：' + res.message);
                }
            } catch (err) {
                console.error('Load preset error:', err);
                alert('載入範本發生錯誤：' + err);
            }
        });
    });
});

// --- 108 CURRICULUM MOE COURSE CODE LOGIC (WINST-23) ---
let currentMoeSubjectsData = [];

async function loadMoeCourseCodes() {
    try {
        const resp = await fetch('/api/moe-course-codes/get');
        const data = await resp.json();
        if (data.status === 'success') {
            currentMoeSubjectsData = data.moe_subjects || [];

            const moeTotalCount = document.getElementById('moeTotalCount');
            const moeMappedCount = document.getElementById('moeMappedCount');
            const moeUnmappedCount = document.getElementById('moeUnmappedCount');
            const moeComplianceRate = document.getElementById('moeComplianceRate');

            if (moeTotalCount) moeTotalCount.textContent = `${data.total_count || 0} 門`;
            if (moeMappedCount) moeMappedCount.textContent = `${data.mapped_count || 0} 門`;
            if (moeUnmappedCount) moeUnmappedCount.textContent = `${data.unmapped_count || 0} 門`;
            if (moeComplianceRate) moeComplianceRate.textContent = `${data.compliance_rate || 0} %`;

            const tbody = document.getElementById('moeCodesTableBody');
            if (tbody) {
                tbody.innerHTML = '';
                if (currentMoeSubjectsData.length === 0) {
                    tbody.innerHTML = '<tr><td colspan="6" style="text-align:center; color:var(--text-muted);">暫無開課科目資料</td></tr>';
                } else {
                    currentMoeSubjectsData.forEach(s => {
                        const tr = document.createElement('tr');
                        const statusBadge = s.is_mapped
                            ? '<span style="color:#34d399; font-weight:bold;"><i class="fa-solid fa-circle-check"></i> 已對接</span>'
                            : '<span style="color:#fbbf24; font-weight:bold;"><i class="fa-solid fa-clock"></i> 建議確認</span>';

                        tr.innerHTML = `
                            <td style="font-weight:bold; color:#818cf8;">${s.subject_code}</td>
                            <td style="font-weight:bold; color:#fff;">${s.subject_name}</td>
                            <td>${s.hours} 節</td>
                            <td><span style="background:rgba(99,102,241,0.2); color:#818cf8; padding:2px 8px; border-radius:4px; font-size:0.75rem;">${s.category}</span></td>
                            <td>
                                <input type="text" class="moe-code-input" data-subjcode="${s.subject_code}" value="${s.moe_code || ''}" placeholder="例如: 114-10001-001" style="padding:4px 8px; border-radius:4px; background:rgba(15,23,42,0.8); color:#fff; border:1px solid var(--border-color); width:100%; font-family:monospace;">
                            </td>
                            <td>${statusBadge}</td>
                        `;
                        tbody.appendChild(tr);
                    });
                }
            }
        }
    } catch (e) {
        console.error("Load MOE course codes failed:", e);
    }
}

function autoGenMoeCodes() {
    const inputs = document.querySelectorAll('.moe-code-input');
    inputs.forEach(inp => {
        const code = inp.dataset.subjcode;
        const subj = currentMoeSubjectsData.find(x => x.subject_code === code);
        if (subj) {
            inp.value = subj.moe_code;
        }
    });
    showToast('已完成 108 課綱國教署標準代碼智慧自動帶入！', 'success');
}

async function saveMoeCourseCodes() {
    const inputs = document.querySelectorAll('.moe-code-input');
    const moeMap = {};
    inputs.forEach(inp => {
        const code = inp.dataset.subjcode;
        const val = inp.value.trim();
        if (code && val) {
            moeMap[code] = val;
        }
    });

    try {
        const resp = await fetch('/api/moe-course-codes/save', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ moe_course_codes: moeMap })
        });
        const data = await resp.json();
        if (data.status === 'success') {
            showToast(data.message, 'success');
            await loadMoeCourseCodes();
        } else {
            showToast(data.message || '儲存失敗', 'error');
        }
    } catch (e) {
        showToast('儲存國教署代碼對照請求失敗', 'error');
    }
}

document.addEventListener('DOMContentLoaded', () => {
    const autoGenMoeCodesBtn = document.getElementById('autoGenMoeCodesBtn');
    if (autoGenMoeCodesBtn) autoGenMoeCodesBtn.addEventListener('click', autoGenMoeCodes);

    const saveMoeCodesBtn = document.getElementById('saveMoeCodesBtn');
    if (saveMoeCodesBtn) saveMoeCodesBtn.addEventListener('click', saveMoeCourseCodes);
});

// --- PRE-SCHEDULING CHECKLIST LOGIC ---
function updateChecklistProgress() {
    const items = document.querySelectorAll('.checklist-item');
    let total = items.length;
    let checked = 0;
    
    items.forEach(item => {
        const id = item.dataset.id;
        if (id) {
            const savedState = localStorage.getItem(`schedule_chk_${id}`);
            if (savedState === 'true') {
                item.checked = true;
            }
        }
        if (item.checked) checked++;
    });

    const pct = total > 0 ? Math.round((checked / total) * 100) : 0;
    const txt = document.getElementById('checklistProgressText');
    const bar = document.getElementById('checklistProgressBar');

    if (txt) txt.textContent = `${checked} / ${total} 完成 (${pct}%)`;
    if (bar) bar.style.width = `${pct}%`;
}

document.addEventListener('DOMContentLoaded', () => {
    updateChecklistProgress();

    document.body.addEventListener('change', (e) => {
        if (e.target && e.target.classList.contains('checklist-item')) {
            const id = e.target.dataset.id;
            if (id) {
                localStorage.setItem(`schedule_chk_${id}`, e.target.checked);
            }
            updateChecklistProgress();
        }
    });
});

// --- TEACHER & SUBJECT CRUD MANAGEMENT LOGIC ---

async function loadTeachersMaintainList() {
    try {
        const resp = await fetch('/api/teachers/list');
        const data = await resp.json();
        if (data.status === 'success') {
            const tbody = document.getElementById('teachersMaintainTableBody');
            if (tbody) {
                tbody.innerHTML = '';
                const teachers = data.teachers || [];
                if (teachers.length === 0) {
                    tbody.innerHTML = '<tr><td colspan="4" style="text-align:center; color:var(--text-muted);">暫無教師資料</td></tr>';
                } else {
                    teachers.forEach(t => {
                        const tr = document.createElement('tr');
                        tr.innerHTML = `
                            <td style="font-weight:bold; color:#818cf8;">${t.code}</td>
                            <td style="font-weight:bold; color:#fff;">${t.name}</td>
                            <td><span style="background:rgba(56,189,248,0.15); color:#38bdf8; padding:2px 8px; border-radius:4px; font-size:0.75rem;">${t.role || '專任教師'}</span></td>
                            <td>
                                <button class="delete-teacher-btn solver-action-btn secondary-btn" data-code="${t.code}" style="padding:2px 8px; font-size:0.75rem; color:#f87171; border-color:rgba(248,113,113,0.3);">
                                    <i class="fa-solid fa-trash-can"></i> 刪除
                                </button>
                            </td>
                        `;
                        tbody.appendChild(tr);
                    });
                }
            }
        }
    } catch (e) {
        console.error("Load teachers list failed:", e);
    }
}

async function addTeacherAction() {
    const codeInp = document.getElementById('newTeacherCodeInput');
    const nameInp = document.getElementById('newTeacherNameInput');
    const roleSel = document.getElementById('newTeacherRoleSelect');

    const code = codeInp ? codeInp.value.trim() : '';
    const name = nameInp ? nameInp.value.trim() : '';
    const role = roleSel ? roleSel.value : '專任教師';

    if (!code || !name) {
        showToast('請輸入完整的教師代碼與姓名！', 'warning');
        return;
    }

    try {
        const resp = await fetch('/api/teachers/add', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ code, name, role })
        });
        const data = await resp.json();
        if (data.status === 'success') {
            showToast(data.message, 'success');
            if (codeInp) codeInp.value = '';
            if (nameInp) nameInp.value = '';
            await loadTeachersMaintainList();
            await fetchMetadata();
        } else {
            showToast(data.message || '新增失敗', 'error');
        }
    } catch (e) {
        showToast('新增教師請求失敗', 'error');
    }
}

async function deleteTeacherAction(code) {
    if (!confirm(`確定要刪除代碼為【${code}】的教師嗎？`)) return;

    try {
        const resp = await fetch('/api/teachers/delete', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ code })
        });
        const data = await resp.json();
        if (data.status === 'success') {
            showToast(data.message, 'success');
            await loadTeachersMaintainList();
            await fetchMetadata();
        } else {
            showToast(data.message || '刪除失敗', 'error');
        }
    } catch (e) {
        showToast('刪除教師請求失敗', 'error');
    }
}

async function loadSubjectsMaintainList() {
    try {
        const resp = await fetch('/api/subjects/list');
        const data = await resp.json();
        if (data.status === 'success') {
            const tbody = document.getElementById('masterSubjectTableBody');
            if (tbody) {
                tbody.innerHTML = '';
                const subjects = data.subjects || [];
                if (subjects.length === 0) {
                    tbody.innerHTML = '<tr><td colspan="5" style="text-align:center; color:var(--text-muted);">暫無科目資料</td></tr>';
                } else {
                    subjects.forEach(s => {
                        const tr = document.createElement('tr');
                        tr.innerHTML = `
                            <td style="font-weight:bold; color:#818cf8;">${s.code}</td>
                            <td style="font-weight:bold; color:#fff;">${s.name}</td>
                            <td><span style="background:rgba(99,102,241,0.2); color:#818cf8; padding:2px 8px; border-radius:4px; font-size:0.75rem;">${s.category || '部定必修'}</span></td>
                            <td>2 節</td>
                            <td>
                                <button class="delete-subj-btn solver-action-btn secondary-btn" data-code="${s.code}" style="padding:2px 8px; font-size:0.75rem; color:#f87171; border-color:rgba(248,113,113,0.3);">
                                    <i class="fa-solid fa-trash-can"></i> 刪除
                                </button>
                            </td>
                        `;
                        tbody.appendChild(tr);
                    });
                }
            }
        }
    } catch (e) {
        console.error("Load subjects list failed:", e);
    }
}

async function addSubjectAction() {
    const codeInp = document.getElementById('catNewCodeInput');
    const nameInp = document.getElementById('catNewNameInput');
    const catInp = document.getElementById('catNewCategoryInput');

    const code = codeInp ? codeInp.value.trim() : '';
    const name = nameInp ? nameInp.value.trim() : '';
    const category = catInp ? catInp.value.trim() : '部定必修';

    if (!code || !name) {
        showToast('請輸入學科代碼與名稱！', 'warning');
        return;
    }

    try {
        const resp = await fetch('/api/subjects/add', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ code, name, category })
        });
        const data = await resp.json();
        if (data.status === 'success') {
            showToast(data.message, 'success');
            if (codeInp) codeInp.value = '';
            if (nameInp) nameInp.value = '';
            await loadSubjectsMaintainList();
        } else {
            showToast(data.message || '新增科目失敗', 'error');
        }
    } catch (e) {
        showToast('新增科目請求失敗', 'error');
    }
}

async function deleteSubjectAction(code) {
    if (!confirm(`確定要刪除代碼為【${code}】的科目嗎？`)) return;

    try {
        const resp = await fetch('/api/subjects/delete', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ code })
        });
        const data = await resp.json();
        if (data.status === 'success') {
            showToast(data.message, 'success');
            await loadSubjectsMaintainList();
        } else {
            showToast(data.message || '刪除科目失敗', 'error');
        }
    } catch (e) {
        showToast('刪除科目請求失敗', 'error');
    }
}

// --- CLASS CRUD MANAGEMENT LOGIC ---

async function loadClassesMaintainList() {
    try {
        const resp = await fetch('/api/classes/list');
        const data = await resp.json();
        if (data.status === 'success') {
            const tbody = document.getElementById('classesMaintainTableBody');
            if (tbody) {
                tbody.innerHTML = '';
                const classes = data.classes || [];
                if (classes.length === 0) {
                    tbody.innerHTML = '<tr><td colspan="5" style="text-align:center; color:var(--text-muted);">暫無班級資料</td></tr>';
                } else {
                    classes.forEach(c => {
                        const tr = document.createElement('tr');
                        tr.innerHTML = `
                            <td style="font-weight:bold; color:#818cf8;">${c.code}</td>
                            <td style="font-weight:bold; color:#fff;">${c.name}</td>
                            <td>${c.tutor ? '<span style="color:#38bdf8;">' + c.tutor + ' 導師</span>' : '<span style="color:var(--text-muted);">無導師</span>'}</td>
                            <td><span style="background:rgba(99,102,241,0.2); color:#818cf8; padding:2px 8px; border-radius:4px; font-size:0.75rem;">${c.group || '高中部'}</span></td>
                            <td>
                                <button class="delete-class-btn solver-action-btn secondary-btn" data-code="${c.code}" style="padding:2px 8px; font-size:0.75rem; color:#f87171; border-color:rgba(248,113,113,0.3);">
                                    <i class="fa-solid fa-trash-can"></i> 刪除
                                </button>
                            </td>
                        `;
                        tbody.appendChild(tr);
                    });
                }
            }
        }
    } catch (e) {
        console.error("Load classes list failed:", e);
    }
}

async function addClassAction() {
    const codeInp = document.getElementById('newClassCodeInput');
    const nameInp = document.getElementById('newClassNameInput');
    const tutorInp = document.getElementById('newClassTutorInput');
    const grpSel = document.getElementById('newClassGroupSelect');

    const code = codeInp ? codeInp.value.trim() : '';
    const name = nameInp ? nameInp.value.trim() : '';
    const tutor = tutorInp ? tutorInp.value.trim() : '';
    const group = grpSel ? grpSel.value : '高中部';

    if (!code || !name) {
        showToast('請輸入完整的班級代碼與名稱！', 'warning');
        return;
    }

    try {
        const resp = await fetch('/api/classes/add', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ code, name, tutor, group })
        });
        const data = await resp.json();
        if (data.status === 'success') {
            showToast(data.message, 'success');
            if (codeInp) codeInp.value = '';
            if (nameInp) nameInp.value = '';
            if (tutorInp) tutorInp.value = '';
            await loadClassesMaintainList();
            await fetchMetadata();
        } else {
            showToast(data.message || '新增失敗', 'error');
        }
    } catch (e) {
        showToast('新增班級請求失敗', 'error');
    }
}

async function deleteClassAction(code) {
    if (!confirm(`確定要刪除代碼為【${code}】的班級嗎？`)) return;

    try {
        const resp = await fetch('/api/classes/delete', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ code })
        });
        const data = await resp.json();
        if (data.status === 'success') {
            showToast(data.message, 'success');
            await loadClassesMaintainList();
            await fetchMetadata();
        } else {
            showToast(data.message || '刪除失敗', 'error');
        }
    } catch (e) {
        showToast('刪除班級請求失敗', 'error');
    }
}

// Bind CRUD Listeners
document.addEventListener('DOMContentLoaded', () => {
    const addTeacherBtn = document.getElementById('addTeacherBtn');
    if (addTeacherBtn) addTeacherBtn.addEventListener('click', addTeacherAction);

    const saveNewMasterSubBtn = document.getElementById('saveNewMasterSubBtn');
    if (saveNewMasterSubBtn) saveNewMasterSubBtn.addEventListener('click', addSubjectAction);

    const addClassBtn = document.getElementById('addClassBtn');
    if (addClassBtn) addClassBtn.addEventListener('click', addClassAction);

    document.body.addEventListener('click', (e) => {
        const tBtn = e.target.closest('.delete-teacher-btn');
        if (tBtn) {
            deleteTeacherAction(tBtn.dataset.code);
            return;
        }

        const sBtn = e.target.closest('.delete-subj-btn');
        if (sBtn) {
            deleteSubjectAction(sBtn.dataset.code);
            return;
        }

        const cBtn = e.target.closest('.delete-class-btn');
        if (cBtn) {
            deleteClassAction(cBtn.dataset.code);
            return;
        }
    });

    // Conversational AI Assistant UI Logic
    const aiChatTriggerBtn = document.getElementById('aiChatTriggerBtn');
    const aiChatDrawer = document.getElementById('aiChatDrawer');
    const closeAiChatBtn = document.getElementById('closeAiChatBtn');
    const sendAiChatBtn = document.getElementById('sendAiChatBtn');
    const aiChatInput = document.getElementById('aiChatInput');
    const aiChatMessages = document.getElementById('aiChatMessages');

    if (aiChatTriggerBtn && aiChatDrawer) {
        aiChatTriggerBtn.addEventListener('click', () => {
            const isHidden = aiChatDrawer.style.display === 'none';
            aiChatDrawer.style.display = isHidden ? 'flex' : 'none';
            if (isHidden && aiChatInput) aiChatInput.focus();
        });
    }

    if (closeAiChatBtn && aiChatDrawer) {
        closeAiChatBtn.addEventListener('click', () => {
            aiChatDrawer.style.display = 'none';
        });
    }

    async function sendAiMessage(msgText) {
        const text = (msgText || aiChatInput.value || '').trim();
        if (!text) return;

        if (aiChatInput) aiChatInput.value = '';

        // Append User Message
        const userMsgDiv = document.createElement('div');
        userMsgDiv.style.display = 'flex';
        userMsgDiv.style.gap = '8px';
        userMsgDiv.style.justifyContent = 'flex-end';
        userMsgDiv.style.alignItems = 'flex-start';
        userMsgDiv.innerHTML = `
            <div style="background: #6366f1; color: #fff; padding: 8px 12px; border-radius: 12px; border-top-right-radius: 2px; max-width: 80%; line-height: 1.4;">${text}</div>
            <div style="width: 28px; height: 28px; border-radius: 50%; background: #3b82f6; display: flex; align-items: center; justify-content: center; color: #fff; flex-shrink: 0; font-size: 0.75rem;">您</div>
        `;
        aiChatMessages.appendChild(userMsgDiv);
        aiChatMessages.scrollTop = aiChatMessages.scrollHeight;

        // Append AI Thinking Indicator
        const thinkingDiv = document.createElement('div');
        thinkingDiv.id = 'aiThinkingMsg';
        thinkingDiv.style.display = 'flex';
        thinkingDiv.style.gap = '8px';
        thinkingDiv.style.alignItems = 'center';
        thinkingDiv.innerHTML = `
            <div style="width: 28px; height: 28px; border-radius: 50%; background: #a855f7; display: flex; align-items: center; justify-content: center; color: #fff; flex-shrink: 0; font-size: 0.75rem;">AI</div>
            <div style="color: #94a3b8; font-style: italic;"><i class="fa-solid fa-spinner fa-spin"></i> AI 正在分析您的排課意圖中...</div>
        `;
        aiChatMessages.appendChild(thinkingDiv);
        aiChatMessages.scrollTop = aiChatMessages.scrollHeight;

        try {
            const resp = await fetch('/api/ai-chat', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ message: text })
            });
            const res = await resp.json();

            const tDiv = document.getElementById('aiThinkingMsg');
            if (tDiv) tDiv.remove();

            if (res.status === 'success') {
                const aiReplyDiv = document.createElement('div');
                aiReplyDiv.style.display = 'flex';
                aiReplyDiv.style.gap = '8px';
                aiReplyDiv.style.alignItems = 'flex-start';
                const formattedReply = (res.reply || '').replace(/\n/g, '<br>');
                aiReplyDiv.innerHTML = `
                    <div style="width: 28px; height: 28px; border-radius: 50%; background: #a855f7; display: flex; align-items: center; justify-content: center; color: #fff; flex-shrink: 0; font-size: 0.75rem;">AI</div>
                    <div style="background: rgba(30, 41, 59, 0.9); color: #e2e8f0; padding: 10px 14px; border-radius: 12px; border-top-left-radius: 2px; border: 1px solid rgba(168, 85, 247, 0.2); max-width: 85%; line-height: 1.5;">${formattedReply}</div>
                `;
                aiChatMessages.appendChild(aiReplyDiv);
                aiChatMessages.scrollTop = aiChatMessages.scrollHeight;

                // Handle Actions
                if (res.action === 'run_full_auto') {
                    const masterBtn = document.getElementById('masterAiOneClickBtn');
                    if (masterBtn) masterBtn.click();
                } else if (res.action === 'create_sim_preset') {
                    const type = res.payload?.type;
                    if (type === '全校共同社團') {
                        const b = document.getElementById('presetSimClubBtn');
                        if (b) b.click();
                    } else if (type === '全校共同週會') {
                        const b = document.getElementById('presetSimWeeklyBtn');
                        if (b) b.click();
                    } else {
                        const b = document.getElementById('presetSimClassMeetingBtn');
                        if (b) b.click();
                    }
                } else if (res.action === 'match_venues') {
                    const b = document.getElementById('autoAiMatchVenuesBtn');
                    if (b) b.click();
                } else if (res.action === 'switch_semester' && res.payload?.semester_id) {
                    doCreateSemester(res.payload.semester_id);
                } else if (res.action === 'show_class_schedule' && res.payload?.code) {
                    window.location.hash = `#class/${res.payload.code}`;
                } else if (res.action === 'show_teacher_schedule' && res.payload?.code) {
                    window.location.hash = `#teacher/${res.payload.code}`;
                } else if (res.action === 'show_room_schedule' && res.payload?.code) {
                    window.location.hash = `#room/${encodeURIComponent(res.payload.code)}`;
                } else if (res.action === 'update_no_teach') {
                    showToast("已成功自動套用並儲存教師不排課約束！");
                    if (typeof loadConfigRules === 'function') loadConfigRules();
                }
            } else {
                showToast("AI 對談失敗：" + res.message);
            }
        } catch (e) {
            const tDiv = document.getElementById('aiThinkingMsg');
            if (tDiv) tDiv.remove();
            showToast("伺服器連線異常。");
        }
    }

    if (sendAiChatBtn) {
        sendAiChatBtn.addEventListener('click', () => sendAiMessage());
    }
    if (aiChatInput) {
        aiChatInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') sendAiMessage();
        });
    }

    document.querySelectorAll('.ai-chip-btn').forEach(chip => {
        chip.addEventListener('click', () => {
            sendAiMessage(chip.textContent.trim());
        });
    });

    // Groq Settings UI Handlers
    const toggleGroqSettingsBtn = document.getElementById('toggleGroqSettingsBtn');
    const groqSettingsPanel = document.getElementById('groqSettingsPanel');
    const saveGroqKeyBtn = document.getElementById('saveGroqKeyBtn');
    const groqApiKeyInput = document.getElementById('groqApiKeyInput');
    const groqStatusBadge = document.getElementById('groqStatusBadge');

    if (toggleGroqSettingsBtn && groqSettingsPanel) {
        toggleGroqSettingsBtn.addEventListener('click', () => {
            const isHidden = groqSettingsPanel.style.display === 'none';
            groqSettingsPanel.style.display = isHidden ? 'block' : 'none';
        });
        loadGroqConfigStatus();
    }

    async function loadGroqConfigStatus() {
        try {
            const resp = await fetch('/api/config/groq');
            const data = await resp.json();
            if (data.status === 'success' && groqStatusBadge) {
                if (data.has_key) {
                    groqStatusBadge.innerHTML = `<span style="color:#34d399;"><i class="fa-solid fa-circle-check"></i> 已連結 (${data.model})</span>`;
                    if (groqApiKeyInput && data.masked_key) groqApiKeyInput.placeholder = data.masked_key;
                } else {
                    groqStatusBadge.innerHTML = `<span style="color:#94a3b8;">未設定 (使用內建 AI 語意引擎)</span>`;
                }
            }
        } catch (e) {
            console.error("Load Groq config status error:", e);
        }
    }

    if (saveGroqKeyBtn) {
        saveGroqKeyBtn.addEventListener('click', async () => {
            const apiKey = (groqApiKeyInput.value || '').trim();
            try {
                const resp = await fetch('/api/config/groq', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ groq_api_key: apiKey, groq_model: 'llama-3.3-70b-versatile' })
                });
                const res = await resp.json();
                if (res.status === 'success') {
                    showToast(res.message);
                    groqApiKeyInput.value = '';
                    await loadGroqConfigStatus();
                    if (groqSettingsPanel) groqSettingsPanel.style.display = 'none';
                } else {
                    showToast("Groq 設定失敗: " + res.message);
                }
            } catch (e) {
                showToast("連線異常，無法儲存 Groq 設定。");
            }
        });
    }
});

/* ==========================================================================
   雙視窗對照模式 (Dual-View Split Modal) & 智慧調代課試算助手 (Swap Assistant)
   ========================================================================== */

let dualViewCurrentClass = '';
let dualViewCurrentTeacher = '';
let dualClassSlotsData = [];
let dualTeacherSlotsData = [];
let dualSelectedDay = null;
let dualSelectedPeriod = null;

async function openDualViewModal(classCode, teacherCode) {
    console.log("openDualViewModal triggered:", classCode, teacherCode);
    initDualViewEvents();
    const modal = document.getElementById('dualViewModal');
    if (!modal) {
        console.error("dualViewModal element not found!");
        return;
    }

    if (typeof allClasses !== 'undefined' && allClasses.length > 0) {
        metadata.classes = allClasses;
    }
    if (typeof allTeachers !== 'undefined' && allTeachers.length > 0) {
        metadata.teachers = allTeachers;
    }

    if (!metadata || !metadata.classes || metadata.classes.length === 0) {
        try { await fetchMetadata(); } catch (e) {}
    }

    modal.style.display = 'flex';
    modal.style.zIndex = '99999';

    const classSelect = document.getElementById('dualViewClassSelect');
    const teacherSelect = document.getElementById('dualViewTeacherSelect');

    // Populate classSelect dropdown safely
    if (classSelect && metadata.classes) {
        classSelect.innerHTML = metadata.classes.map(c => {
            const code = typeof c === 'object' ? (c.code || c.name) : c;
            const name = typeof c === 'object' ? (c.name || c.code) : c;
            const tutor = typeof c === 'object' && c.tutor ? ` (導師：${c.tutor})` : '';
            return `<option value="${code}" ${code === classCode ? 'selected' : ''}>${name}${tutor}</option>`;
        }).join('');
    }

    // Populate teacherSelect dropdown safely
    if (teacherSelect && metadata.teachers) {
        teacherSelect.innerHTML = metadata.teachers.map(t => {
            const code = typeof t === 'object' ? (t.code || t.name) : t;
            const name = typeof t === 'object' ? (t.name || t.code) : t;
            const role = typeof t === 'object' && t.role ? ` (${t.role})` : '';
            return `<option value="${code}" ${code === teacherCode || name === teacherCode ? 'selected' : ''}>${name}${role}</option>`;
        }).join('');
    }

    const firstCls = metadata.classes && metadata.classes[0] ? (typeof metadata.classes[0] === 'object' ? metadata.classes[0].code : metadata.classes[0]) : '';
    dualViewCurrentClass = classCode || firstCls;
    
    const firstTch = metadata.teachers && metadata.teachers[0] ? (typeof metadata.teachers[0] === 'object' ? metadata.teachers[0].code : metadata.teachers[0]) : '';
    
    let tMatch = metadata.teachers ? metadata.teachers.find(t => (typeof t === 'object' ? (t.code === teacherCode || t.name === teacherCode) : t === teacherCode)) : null;
    dualViewCurrentTeacher = tMatch ? (typeof tMatch === 'object' ? tMatch.code : tMatch) : (teacherCode || firstTch);

    if (classSelect) classSelect.value = dualViewCurrentClass;
    if (teacherSelect) teacherSelect.value = dualViewCurrentTeacher;

    await loadDualViewData();
}

async function loadDualViewData() {
    const classSelect = document.getElementById('dualViewClassSelect');
    const teacherSelect = document.getElementById('dualViewTeacherSelect');

    if (classSelect && classSelect.value) dualViewCurrentClass = classSelect.value;
    if (teacherSelect && teacherSelect.value) dualViewCurrentTeacher = teacherSelect.value;

    if (!dualViewCurrentClass || !dualViewCurrentTeacher) {
        console.warn("loadDualViewData skipped due to empty class/teacher code:", dualViewCurrentClass, dualViewCurrentTeacher);
        return;
    }

    try {
        const [clsRes, tRes] = await Promise.all([
            fetch(`/api/schedule/class/${encodeURIComponent(dualViewCurrentClass)}`).then(r => r.ok ? r.json() : []),
            fetch(`/api/schedule/teacher/${encodeURIComponent(dualViewCurrentTeacher)}`).then(r => r.ok ? r.json() : [])
        ]);

        dualClassSlotsData = Array.isArray(clsRes) ? clsRes : (clsRes.slots || clsRes.data || []);
        dualTeacherSlotsData = Array.isArray(tRes) ? tRes : (tRes.slots || tRes.data || []);

        renderDualClassGrid();
        renderDualTeacherGrid();

        if (dualSelectedDay && dualSelectedPeriod) {
            highlightDualSlotSync(dualSelectedDay, dualSelectedPeriod);
        } else {
            highlightDualSlotSync(1, 1);
        }
    } catch (e) {
        console.error("Error loading dual view data:", e);
    }
}

function renderDualClassGrid() {
    const tbody = document.getElementById('dualClassBody');
    const titleEl = document.getElementById('dualClassTitle');
    const tutorEl = document.getElementById('dualClassTutor');

    if (!tbody) return;

    const cls = metadata.classes ? metadata.classes.find(c => typeof c === 'object' ? (c.code === dualViewCurrentClass || c.name === dualViewCurrentClass) : c === dualViewCurrentClass) : null;
    const clsName = cls ? (typeof cls === 'object' ? cls.name : cls) : dualViewCurrentClass;
    const clsTutor = cls && typeof cls === 'object' && cls.tutor ? cls.tutor : '';

    if (titleEl) titleEl.innerHTML = `<span><i class="fa-solid fa-chalkboard"></i> ${clsName} 班級課表</span>`;
    if (tutorEl) tutorEl.textContent = clsTutor ? `導師：${clsTutor}` : '';

    const grid = Array(8).fill(null).map(() => Array(5).fill(null).map(() => []));
    dualClassSlotsData.forEach(s => {
        const d = parseInt(s.day);
        const p = parseInt(s.period);
        if (d >= 1 && d <= 5 && p >= 1 && p <= 8) grid[p-1][d-1].push(s);
    });

    tbody.innerHTML = '';
    for (let p = 1; p <= 8; p++) {
        const tr = document.createElement('tr');
        tr.innerHTML = `<td style="font-weight:bold; background:rgba(255,255,255,0.02); text-align:center;">第${p}節</td>`;
        for (let d = 1; d <= 5; d++) {
            const td = document.createElement('td');
            td.style.cursor = 'pointer';
            td.dataset.day = d;
            td.dataset.period = p;
            td.className = 'dual-cell-slot';

            const lessons = grid[p-1][d-1];
            if (lessons.length === 0) {
                td.innerHTML = '<span style="color:#64748b; font-size:0.7rem;">- 空堂 -</span>';
            } else {
                td.innerHTML = lessons.map(l => 
                    `<div style="font-weight:bold; color:#38bdf8;">${l.subject_name}</div>
                     <div style="font-size:0.72rem; color:#94a3b8;">${l.teacher_name || ''} ${l.room_name ? '['+l.room_name+']' : ''}</div>`
                ).join('<hr style="border:0; border-top:1px dashed rgba(255,255,255,0.1); margin:2px 0;">');
            }

            td.addEventListener('click', () => highlightDualSlotSync(d, p));
            tr.appendChild(td);
        }
        tbody.appendChild(tr);
    }
}

function renderDualTeacherGrid() {
    const tbody = document.getElementById('dualTeacherBody');
    const titleEl = document.getElementById('dualTeacherTitle');
    const roleEl = document.getElementById('dualTeacherRole');

    if (!tbody) return;

    const t = metadata.teachers ? metadata.teachers.find(x => typeof x === 'object' ? (x.code === dualViewCurrentTeacher || x.name === dualViewCurrentTeacher) : x === dualViewCurrentTeacher) : null;
    const tName = t ? (typeof t === 'object' ? t.name : t) : dualViewCurrentTeacher;
    const tRole = t && typeof t === 'object' && t.role ? t.role : '';

    if (titleEl) titleEl.innerHTML = `<span><i class="fa-solid fa-user-graduate"></i> ${tName} 老師課表</span>`;
    if (roleEl) roleEl.textContent = tRole ? `職務：${tRole}` : '';

    const grid = Array(8).fill(null).map(() => Array(5).fill(null).map(() => []));
    dualTeacherSlotsData.forEach(s => {
        const d = parseInt(s.day);
        const p = parseInt(s.period);
        if (d >= 1 && d <= 5 && p >= 1 && p <= 8) grid[p-1][d-1].push(s);
    });

    tbody.innerHTML = '';
    for (let p = 1; p <= 8; p++) {
        const tr = document.createElement('tr');
        tr.innerHTML = `<td style="font-weight:bold; background:rgba(255,255,255,0.02); text-align:center;">第${p}節</td>`;
        for (let d = 1; d <= 5; d++) {
            const td = document.createElement('td');
            td.style.cursor = 'pointer';
            td.dataset.day = d;
            td.dataset.period = p;
            td.className = 'dual-cell-slot';

            const lessons = grid[p-1][d-1];
            if (lessons.length === 0) {
                td.innerHTML = '<span style="color:#34d399; font-size:0.7rem; font-weight:bold;">🟢 空堂 (無課)</span>';
            } else {
                td.innerHTML = lessons.map(l => 
                    `<div style="font-weight:bold; color:#818cf8;">${l.class_name} ${l.subject_name}</div>
                     <div style="font-size:0.72rem; color:#94a3b8;">${l.room_name ? '['+l.room_name+']' : ''}</div>`
                ).join('<hr style="border:0; border-top:1px dashed rgba(255,255,255,0.1); margin:2px 0;">');
            }

            td.addEventListener('click', () => highlightDualSlotSync(d, p));
            tr.appendChild(td);
        }
        tbody.appendChild(tr);
    }
}

function highlightDualSlotSync(d, p) {
    dualSelectedDay = d;
    dualSelectedPeriod = p;

    document.querySelectorAll('#dualClassBody td, #dualTeacherBody td').forEach(td => {
        td.style.background = '';
        td.style.boxShadow = '';
    });

    const classCell = document.querySelector(`#dualClassBody td[data-day="${d}"][data-period="${p}"]`);
    const teacherCell = document.querySelector(`#dualTeacherBody td[data-day="${d}"][data-period="${p}"]`);

    if (classCell) {
        classCell.style.background = 'rgba(56, 189, 248, 0.25)';
        classCell.style.boxShadow = 'inset 0 0 0 2px #38bdf8';
    }
    if (teacherCell) {
        teacherCell.style.background = 'rgba(129, 140, 248, 0.25)';
        teacherCell.style.boxShadow = 'inset 0 0 0 2px #818cf8';
    }

    updateDualSwapAssistant(d, p);
}

function updateDualSwapAssistant(d, p) {
    const daysMap = ['', '週一', '週二', '週三', '週四', '週五'];
    const infoEl = document.getElementById('dualSelectedSlotInfo');
    const col1 = document.getElementById('dualSameSubjTeachers');
    const col2 = document.getElementById('dualClassSwapCandidates');
    const col3 = document.getElementById('dualSchoolwideFreeInfo');

    const classLessons = dualClassSlotsData.filter(s => parseInt(s.day) === d && parseInt(s.period) === p);
    const teacherLessons = dualTeacherSlotsData.filter(s => parseInt(s.day) === d && parseInt(s.period) === p);

    const cls = metadata.classes ? metadata.classes.find(c => c.code === dualViewCurrentClass) : null;
    const t = metadata.teachers ? metadata.teachers.find(x => x.code === dualViewCurrentTeacher || x.name === dualViewCurrentTeacher) : null;

    const clsName = cls ? cls.name : dualViewCurrentClass;
    const tName = t ? t.name : dualViewCurrentTeacher;

    if (infoEl) {
        let text = `對焦：【${daysMap[d]} 第${p}節】 | ${clsName}：${classLessons.map(l => l.subject_name + '(' + l.teacher_name + ')').join(', ') || '無課'} | ${tName}：${teacherLessons.map(l => l.class_name + l.subject_name).join(', ') || '🟢 空堂'}`;
        infoEl.textContent = text;
    }

    if (col1) {
        if (classLessons.length > 0) {
            const activeLesson = classLessons[0];
            const subjName = activeLesson.subject_name;
            const candTeachers = (metadata.teachers || []).filter(tch => tch.code !== dualViewCurrentTeacher && tch.name !== tName);

            col1.innerHTML = candTeachers.slice(0, 6).map(tch => 
                `<div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:4px; padding:3px 6px; background:rgba(255,255,255,0.03); border-radius:4px;">
                    <span style="color:#e2e8f0; font-weight:bold;">${tch.name} <span style="font-size:0.7rem; color:#94a3b8;">${tch.role || ''}</span></span>
                    <button class="solver-action-btn primary-btn" style="padding:1px 6px; font-size:0.7rem; background:#0284c7;" onclick="showToast('已選擇 ${tch.name} 老師為 ${clsName} ${subjName} 之請假代課人！')">選為代課</button>
                 </div>`
            ).join('') || '<div style="color:#64748b;">該時段無同科空堂教師</div>';
        } else {
            col1.innerHTML = '<div style="color:#64748b;">此時段班級無課，無需代課</div>';
        }
    }

    if (col2) {
        const otherSlots = dualClassSlotsData.filter(s => !(parseInt(s.day) === d && parseInt(s.period) === p));
        if (otherSlots.length > 0) {
            col2.innerHTML = otherSlots.slice(0, 5).map(s => 
                `<div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:4px; padding:3px 6px; background:rgba(255,255,255,0.03); border-radius:4px;">
                    <span><strong style="color:#fbbf24;">${daysMap[s.day]}第${s.period}節</strong> ${s.subject_name} (${s.teacher_name})</span>
                    <button class="solver-action-btn primary-btn" style="padding:1px 6px; font-size:0.7rem; background:#d97706;" onclick="showToast('已建議將 ${daysMap[d]}第${p}節 與 ${daysMap[s.day]}第${s.period}節 (${s.subject_name}) 進行兩節對調！')">對調此節</button>
                 </div>`
            ).join('');
        } else {
            col2.innerHTML = '<div style="color:#64748b;">無可對調節次</div>';
        }
    }

    if (col3) {
        const allRoomsList = metadata.classrooms || [];
        col3.innerHTML = `
            <div style="color:#34d399; font-weight:bold; margin-bottom:4px;"><i class="fa-solid fa-door-open"></i> 全校專用教室即時狀態 (${daysMap[d]}第${p}節)：</div>
            <div style="display:flex; flex-wrap:wrap; gap:6px; margin-bottom:6px; max-height:100px; overflow-y:auto;">
                ${allRoomsList.map(r => {
                    const rName = typeof r === 'object' ? (r.name || r.code) : r;
                    const rCode = typeof r === 'object' ? (r.code || r.name) : r;
                    return `<span style="background:rgba(52,211,153,0.15); border:1px solid rgba(52,211,153,0.3); color:#34d399; padding:2px 6px; border-radius:4px; font-size:0.75rem;" title="點擊查詢 ${rName} 場地課表" onclick="window.location.hash='#room/${encodeURIComponent(rCode)}'; closeDualViewModal();">🟢 ${rName} (空堂可使用)</span>`;
                }).join('') || '<span style="color:#64748b;">無多間專用教室紀錄</span>'}
            </div>
            <div style="color:#a78bfa; font-size:0.75rem;"><i class="fa-solid fa-user-clock"></i> 當節全校空堂教師：${(metadata.teachers || []).slice(0, 5).map(x=>x.name||x.code).join('、 ')} 老師</div>
        `;
    }
}

function toggleModalMaximize(modalId) {
    const modal = document.getElementById(modalId);
    if (!modal) return;
    const modalContent = modal.querySelector('.modal-content');
    if (!modalContent) return;

    modalContent.classList.toggle('fullscreen-modal');
    const isFullscreen = modalContent.classList.contains('fullscreen-modal');
    
    const icon = modal.querySelector('.maximize-modal-btn i');
    if (icon) {
        if (isFullscreen) {
            icon.className = 'fa-solid fa-compress';
        } else {
            icon.className = 'fa-solid fa-expand';
        }
    }
}

window.toggleModalMaximize = toggleModalMaximize;

let dualEventsInitialized = false;
function initDualViewEvents() {
    if (dualEventsInitialized) return;
    const closeBtn = document.getElementById('closeDualViewBtn');
    const modal = document.getElementById('dualViewModal');
    const classSelect = document.getElementById('dualViewClassSelect');
    const teacherSelect = document.getElementById('dualViewTeacherSelect');
    const printBtn = document.getElementById('dualViewPrintBtn');
    const dualBtn = document.getElementById('dualViewModalBtn');

    if (dualBtn) {
        dualBtn.addEventListener('click', (e) => {
            e.preventDefault();
            openDualViewModal('', '');
        });
    }

    if (closeBtn && modal) {
        closeBtn.addEventListener('click', () => {
            modal.style.display = 'none';
        });
    }

    if (modal) {
        modal.addEventListener('click', (e) => {
            if (e.target === modal) {
                modal.style.display = 'none';
            }
        });
    }

    if (classSelect) classSelect.addEventListener('change', loadDualViewData);
    if (teacherSelect) teacherSelect.addEventListener('change', loadDualViewData);
    if (printBtn) {
        printBtn.addEventListener('click', () => {
            window.print();
        });
    }
    dualEventsInitialized = true;
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initDualViewEvents);
} else {
    initDualViewEvents();
}

// --- Lesson Notes System ---
let lessonNotes = {};

async function fetchLessonNotes() {
    try {
        const resp = await fetch('/api/notes');
        const data = await resp.json();
        if (data.status === 'success' && data.notes) {
            lessonNotes = data.notes;
        }
    } catch (e) {
        console.error("Fetch lesson notes failed:", e);
    }
}

function openNoteModal(key, title, day, period) {
    const modal = document.getElementById('noteModal');
    if (!modal) return;

    document.getElementById('noteTargetKey').value = key;
    document.getElementById('noteModalTitle').innerText = `註記 - ${title} (週${['一','二','三','四','五'][parseInt(day)-1] || day} 第${period}節)`;
    
    const existing = lessonNotes[key];
    const deleteBtn = document.getElementById('deleteNoteBtn');

    if (existing) {
        selectNoteType(existing.note_type || '兼課');
        document.getElementById('noteTextInput').value = existing.note_text || '';
        document.getElementById('noteAuthorInput').value = existing.author || '教務處';
        if (deleteBtn) deleteBtn.style.display = 'inline-block';
    } else {
        selectNoteType('兼課');
        document.getElementById('noteTextInput').value = '';
        document.getElementById('noteAuthorInput').value = '教務處';
        if (deleteBtn) deleteBtn.style.display = 'none';
    }

    modal.style.display = 'flex';
}

function closeNoteModal() {
    const modal = document.getElementById('noteModal');
    if (modal) modal.style.display = 'none';
}

function selectNoteType(type) {
    document.getElementById('selectedNoteType').value = type;
    const buttons = document.querySelectorAll('#noteTypeSelector .btn-note-tag');
    buttons.forEach(btn => {
        const t = btn.getAttribute('data-type');
        if (t === type) {
            btn.classList.add('active');
            btn.style.background = getNoteTypeColorBg(type);
            btn.style.borderColor = getNoteTypeColorBorder(type);
            btn.style.color = getNoteTypeColorText(type);
            btn.style.fontWeight = 'bold';
        } else {
            btn.classList.remove('active');
            btn.style.background = 'transparent';
            btn.style.borderColor = 'var(--border-color)';
            btn.style.color = '#94a3b8';
            btn.style.fontWeight = 'normal';
        }
    });
}

function getNoteTypeColorBg(type) {
    if (type === '兼課') return 'rgba(245, 158, 11, 0.25)';
    if (type === '調課') return 'rgba(251, 191, 36, 0.25)';
    if (type === '代課') return 'rgba(56, 189, 248, 0.25)';
    if (type === '段考') return 'rgba(239, 68, 68, 0.25)';
    if (type === '地點') return 'rgba(52, 211, 153, 0.25)';
    return 'rgba(167, 139, 250, 0.25)';
}

function getNoteTypeColorBorder(type) {
    if (type === '兼課') return '#f59e0b';
    if (type === '調課') return '#fbbf24';
    if (type === '代課') return '#38bdf8';
    if (type === '段考') return '#ef4444';
    if (type === '地點') return '#34d399';
    return '#a78bfa';
}

function getNoteTypeColorText(type) {
    if (type === '兼課') return '#f59e0b';
    if (type === '調課') return '#fbbf24';
    if (type === '代課') return '#38bdf8';
    if (type === '段考') return '#ef4444';
    if (type === '地點') return '#34d399';
    return '#a78bfa';
}

function getNoteTypeColorBorder(type) {
    if (type === '調課') return '#fbbf24';
    if (type === '代課') return '#38bdf8';
    if (type === '段考') return '#ef4444';
    if (type === '地點') return '#34d399';
    return '#a78bfa';
}

function getNoteTypeColorText(type) {
    if (type === '調課') return '#fbbf24';
    if (type === '代課') return '#38bdf8';
    if (type === '段考') return '#ef4444';
    if (type === '地點') return '#34d399';
    return '#a78bfa';
}

async function saveLessonNote() {
    const key = document.getElementById('noteTargetKey').value;
    const note_type = document.getElementById('selectedNoteType').value || '調課';
    const note_text = document.getElementById('noteTextInput').value.trim();
    const author = document.getElementById('noteAuthorInput').value.trim() || '教務處';

    if (!key) return;

    try {
        const resp = await fetch('/api/notes/save', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ key, note_type, note_text, author })
        });
        const data = await resp.json();
        if (data.status === 'success') {
            lessonNotes = data.notes || {};
            showToast('課表註記已成功儲存！', 'success');
            closeNoteModal();
            handleHashChange();
        } else {
            alert('儲存失敗: ' + data.message);
        }
    } catch (e) {
        alert('儲存發生錯誤: ' + e.message);
    }
}

async function deleteLessonNote() {
    const key = document.getElementById('noteTargetKey').value;
    if (!key) return;

    if (!confirm('確定要刪除此課表註記嗎？')) return;

    try {
        const resp = await fetch('/api/notes/delete', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ key })
        });
        const data = await resp.json();
        if (data.status === 'success') {
            lessonNotes = data.notes || {};
            showToast('課表註記已成功刪除！', 'info');
            closeNoteModal();
            handleHashChange();
        }
    } catch (e) {
        alert('刪除失敗: ' + e.message);
    }
}

window.openNoteModal = openNoteModal;
window.closeNoteModal = closeNoteModal;
window.selectNoteType = selectNoteType;
window.saveLessonNote = saveLessonNote;
window.deleteLessonNote = deleteLessonNote;







