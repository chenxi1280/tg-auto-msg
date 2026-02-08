// H5 控制台 JavaScript

// API 基础路径
const API_BASE = '/api';

// 工具函数
function formatDate(timestamp) {
    if (!timestamp) return '未设置';
    return new Date(timestamp * 1000).toLocaleString('zh-CN');
}

function formatTimeRange(start, end) {
    if (start === null || end === null) return '全天';
    return `${start}:00 - ${end}:00`;
}

// 获取任务列表
async function fetchTasks() {
    try {
        const response = await fetch(`${API_BASE}/tasks`);
        const data = await response.json();
        return data;
    } catch (error) {
        console.error('获取任务列表失败:', error);
        return { success: false, error };
    }
}

// 获取单个任务
async function fetchTask(taskId) {
    try {
        const response = await fetch(`${API_BASE}/tasks/${taskId}`);
        const data = await response.json();
        return data;
    } catch (error) {
        console.error('获取任务详情失败:', error);
        return { success: false, error };
    }
}

// 更新任务
async function updateTask(taskId, taskData) {
    try {
        const response = await fetch(`${API_BASE}/tasks/${taskId}`, {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(taskData)
        });
        const data = await response.json();
        return data;
    } catch (error) {
        console.error('更新任务失败:', error);
        return { success: false, error };
    }
}

// 创建任务
async function createTask(taskData) {
    try {
        const response = await fetch(`${API_BASE}/tasks`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(taskData)
        });
        const data = await response.json();
        return data;
    } catch (error) {
        console.error('创建任务失败:', error);
        return { success: false, error };
    }
}

// 删除任务
async function deleteTask(taskId) {
    try {
        const response = await fetch(`${API_BASE}/tasks/${taskId}`, {
            method: 'DELETE'
        });
        const data = await response.json();
        return data;
    } catch (error) {
        console.error('删除任务失败:', error);
        return { success: false, error };
    }
}

// 获取任务日志
async function fetchTaskLogs(taskId, limit = 50) {
    try {
        const response = await fetch(`${API_BASE}/tasks/${taskId}/logs?limit=${limit}`);
        const data = await response.json();
        return data;
    } catch (error) {
        console.error('获取任务日志失败:', error);
        return { success: false, error };
    }
}

// 批量更新任务
async function batchUpdateTasks(taskIds, updateData) {
    try {
        const response = await fetch(`${API_BASE}/tasks/batch`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                task_ids: taskIds,
                update_data: updateData
            })
        });
        const data = await response.json();
        return data;
    } catch (error) {
        console.error('批量更新失败:', error);
        return { success: false, error };
    }
}

// Toast 提示
function showToast(message, type = 'info') {
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.textContent = message;
    document.body.appendChild(toast);

    setTimeout(() => {
        toast.classList.add('show');
    }, 10);

    setTimeout(() => {
        toast.classList.remove('show');
        setTimeout(() => toast.remove(), 300);
    }, 3000);
}

// 确认对话框
function confirmDialog(message, onConfirm) {
    const modal = document.createElement('div');
    modal.className = 'modal';
    modal.innerHTML = `
        <div class="modal-content">
            <div class="modal-header">
                <h3>确认</h3>
                <button class="modal-close">&times;</button>
            </div>
            <div class="modal-body">
                <p>${message}</p>
            </div>
            <div class="modal-footer">
                <button class="btn btn-secondary modal-cancel">取消</button>
                <button class="btn btn-danger modal-confirm">确认</button>
            </div>
        </div>
    `;

    document.body.appendChild(modal);

    const closeBtn = modal.querySelector('.modal-close');
    const cancelBtn = modal.querySelector('.modal-cancel');
    const confirmBtn = modal.querySelector('.modal-confirm');

    const closeModal = () => {
        modal.remove();
    };

    closeBtn.addEventListener('click', closeModal);
    cancelBtn.addEventListener('click', closeModal);
    confirmBtn.addEventListener('click', () => {
        closeModal();
        onConfirm();
    });

    // 点击背景关闭
    modal.addEventListener('click', (e) => {
        if (e.target === modal) {
            closeModal();
        }
    });
}

// 加载动画
function showLoading(element) {
    element.innerHTML = '<div class="loading"><div class="spinner"></div></div>';
}

function hideLoading(element) {
    const loading = element.querySelector('.loading');
    if (loading) {
        loading.remove();
    }
}

// 按钮编辑器
class ButtonEditor {
    constructor(containerId) {
        this.container = document.getElementById(containerId);
    }

    addRow() {
        const row = document.createElement('div');
        row.className = 'button-row';
        row.innerHTML = `
            <div class="button-item">
                <input type="text" class="button-text" placeholder="按钮文字">
                <input type="url" class="button-url" placeholder="URL">
                <button class="btn btn-danger btn-sm" onclick="this.closest('.button-item').remove()">×</button>
            </div>
        `;
        this.container.appendChild(row);
    }

    addButtonToRow(rowIndex) {
        const rows = this.container.querySelectorAll('.button-row');
        if (rows[rowIndex]) {
            const item = document.createElement('div');
            item.className = 'button-item';
            item.innerHTML = `
                <input type="text" class="button-text" placeholder="按钮文字">
                <input type="url" class="button-url" placeholder="URL">
                <button class="btn btn-danger btn-sm" onclick="this.closest('.button-item').remove()">×</button>
            `;
            rows[rowIndex].appendChild(item);
        }
    }

    getData() {
        const buttons = [];
        const rows = this.container.querySelectorAll('.button-row');

        rows.forEach(row => {
            const rowButtons = [];
            const items = row.querySelectorAll('.button-item');

            items.forEach(item => {
                const text = item.querySelector('.button-text').value.trim();
                const url = item.querySelector('.button-url').value.trim();
                if (text && url) {
                    rowButtons.push({ text, url });
                }
            });

            if (rowButtons.length > 0) {
                buttons.push(rowButtons);
            }
        });

        return buttons;
    }

    setData(buttons) {
        this.container.innerHTML = '';
        if (!buttons || buttons.length === 0) {
            this.addRow();
            return;
        }

        buttons.forEach(row => {
            const rowDiv = document.createElement('div');
            rowDiv.className = 'button-row';

            row.forEach(btn => {
                const item = document.createElement('div');
                item.className = 'button-item';
                item.innerHTML = `
                    <input type="text" class="button-text" value="${btn.text || ''}" placeholder="按钮文字">
                    <input type="url" class="button-url" value="${btn.url || ''}" placeholder="URL">
                    <button class="btn btn-danger btn-sm" onclick="this.closest('.button-item').remove()">×</button>
                `;
                rowDiv.appendChild(item);
            });

            this.container.appendChild(rowDiv);
        });
    }
}

// 媒体上传
class MediaUploader {
    constructor(inputId, statusId) {
        this.input = document.getElementById(inputId);
        this.status = document.getElementById(statusId);
        this.fileData = null;

        this.input.addEventListener('change', (e) => this.handleFile(e));
    }

    async handleFile(e) {
        const file = e.target.files[0];
        if (!file) return;

        this.status.textContent = '上传中...';

        try {
            const formData = new FormData();
            formData.append('file', file);

            const response = await fetch('/api/media/upload', {
                method: 'POST',
                body: formData
            });

            const data = await response.json();

            if (data.success) {
                this.fileData = data.data;
                this.status.textContent = `${data.data.media_type}: ${data.data.file_id}`;
                showToast('媒体上传成功', 'success');
            } else {
                this.status.textContent = '上传失败';
                showToast('媒体上传失败', 'error');
            }
        } catch (error) {
            console.error('上传错误:', error);
            this.status.textContent = '上传失败';
            showToast('媒体上传失败', 'error');
        }
    }

    getData() {
        return this.fileData;
    }

    setData(mediaData) {
        if (mediaData) {
            this.fileData = mediaData;
            this.status.textContent = `${mediaData.media_type}: ${mediaData.file_id}`;
        } else {
            this.fileData = null;
            this.status.textContent = '未上传';
        }
    }
}

// 导出
window.ButtonEditor = ButtonEditor;
window.MediaUploader = MediaUploader;
window.showToast = showToast;
window.confirmDialog = confirmDialog;
