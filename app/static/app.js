// SecureShare Vue.js Application
const { createApp, ref, onMounted } = Vue;

createApp({
    setup() {
        // Reactive State
        const authenticated = ref(false);
        const selectedFile = ref(null);
        const uploading = ref(false);
        const maxDownloads = ref(null);
        const expirationDays = ref(1);
        const uploadResult = ref(null);
        const files = ref([]);
        const fileInput = ref(null);
        const isDragging = ref(false);
        const appConfig = ref({ title: 'Simple Filedrop', subtitle: 'Simple file sharing', max_file_size: 100 * 1024 * 1024 });

        const uploadProgress = ref(0);
        const uploadMessage = ref('');
        let xhr = null;

        // Authentication Functions
        const checkAuth = async () => {
            try {
                const response = await fetch('/auth/me');
                const data = await response.json();
                authenticated.value = data.authenticated;
            } catch (error) {
                console.error('Auth check failed:', error);
            }
        };

        const loadConfig = async () => {
            try {
                const response = await fetch('/api/config');
                if (response.ok) {
                    appConfig.value = await response.json();
                    document.title = `${appConfig.value.title} - ${appConfig.value.subtitle}`;
                }
            } catch (error) {
                console.error('Failed to load config:', error);
            }
        };

        const login = () => {
            window.location.href = '/auth/login';
        };

        const logout = async () => {
            try {
                await fetch('/auth/logout', { method: 'POST' });
                authenticated.value = false;
                files.value = [];
                uploadResult.value = null;
            } catch (error) {
                console.error('Logout failed:', error);
            }
        };

        // File Handling Functions
        const fileSelected = (event) => {
            const file = event.target.files[0];
            if (file) {
                selectedFile.value = file;
                uploadResult.value = null;
            }
        };

        const handleDrop = (event) => {
            event.preventDefault();
            isDragging.value = false;
            
            const droppedFiles = event.dataTransfer.files;
            if (droppedFiles.length > 0) {
                selectedFile.value = droppedFiles[0];
                uploadResult.value = null;
            }
        };

        const upload = async () => {
            if (!selectedFile.value) return;

            // Client-side file size validation using server config
            const maxFileSize = appConfig.value.max_file_size;
            if (selectedFile.value.size > maxFileSize) {
                uploadMessage.value = `File too large. Maximum size: ${Math.round(maxFileSize / (1024*1024))}MB`;
                return;
            }

            uploading.value = true;
            uploadProgress.value = 0;
            uploadMessage.value = 'Preparing upload...';
            uploadResult.value = null;

            const formData = new FormData();
            formData.append('file', selectedFile.value);
            if (maxDownloads.value) {
                formData.append('max_downloads', maxDownloads.value);
            }
            formData.append('expiration_days', expirationDays.value);

            xhr = new XMLHttpRequest();

            xhr.upload.addEventListener('progress', (event) => {
                if (event.lengthComputable) {
                    const percentage = Math.round((event.loaded / event.total) * 100);
                    uploadProgress.value = percentage;
                    uploadMessage.value = `Uploading... ${percentage}%`;
                }
            });

            xhr.addEventListener('load', () => {
                uploading.value = false;
                if (xhr.status >= 200 && xhr.status < 300) {
                    uploadProgress.value = 100;
                    uploadMessage.value = 'Upload complete!';
                    uploadResult.value = JSON.parse(xhr.responseText);
                    fileInput.value.value = '';
                    selectedFile.value = null;
                    maxDownloads.value = null;
                    loadFiles();
                } else {
                    // Try to parse server error message
                    try {
                        const errorData = JSON.parse(xhr.responseText);
                        uploadMessage.value = errorData.detail || 'Upload failed';
                    } catch {
                        uploadMessage.value = xhr.statusText || 'Upload failed';
                    }
                }
            });

            xhr.addEventListener('error', () => {
                uploading.value = false;
                uploadMessage.value = 'An error occurred during the upload.';
            });

            xhr.addEventListener('abort', () => {
                uploading.value = false;
                uploadMessage.value = 'Upload canceled.';
            });

            xhr.addEventListener('timeout', () => {
                uploading.value = false;
                uploadMessage.value = 'Upload timed out. Try uploading a smaller file or check your connection.';
            });

            xhr.open('POST', '/api/upload', true);
            xhr.timeout = 300000; // 5 minutes timeout for large files
            xhr.send(formData);
        };

        const cancelUpload = () => {
            if (xhr) {
                xhr.abort();
            }
        };

        // File Management Functions
        const loadFiles = async () => {
            try {
                const response = await fetch('/api/files');
                if (response.ok) {
                    files.value = await response.json();
                }
            } catch (error) {
                console.error('Failed to load files:', error);
            }
        };

        const deleteFile = async (id) => {
            try { 
                await fetch(`/api/files/${id}`, {method: 'DELETE'}); 
                loadFiles(); 
            } catch(e) {}
        };

        // Utility Functions
        const copyUrl = async () => {
            if (!uploadResult.value) return;
            
            const url = `${window.location.origin}/share/${uploadResult.value.token}`;
            try {
                await navigator.clipboard.writeText(url);
                // Could add a toast notification here
            } catch (error) {
                console.error('Failed to copy URL:', error);
            }
        };

        const copyShareUrl = async (token) => {
            const url = `${window.location.origin}/share/${token}`;
            try {
                await navigator.clipboard.writeText(url);
                // Could add a toast notification here
            } catch (error) {
                console.error('Failed to copy URL:', error);
            }
        };

        const downloadFile = (token, filename) => {
            const url = `${window.location.origin}/share/${token}`;
            const link = document.createElement('a');
            link.href = url;
            link.download = filename;
            document.body.appendChild(link);
            link.click();
            document.body.removeChild(link);
        };

        const formatFileSize = (bytes) => {
            if (bytes === 0) return '0 Bytes';
            
            const k = 1024;
            const sizes = ['Bytes', 'KB', 'MB', 'GB', 'TB'];
            const i = Math.floor(Math.log(bytes) / Math.log(k));
            
            return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
        };

        const formatDate = (dateString) => {
            const expirationDate = new Date(dateString);
            const now = new Date();
            const diffTime = expirationDate - now;
            
            // If expired (negative difference)
            if (diffTime <= 0) {
                return 'Expired';
            }
            
            const diffHours = Math.floor(diffTime / (1000 * 60 * 60));
            const diffDays = Math.floor(diffTime / (1000 * 60 * 60 * 24));
            
            if (diffHours < 24) {
                if (diffHours < 1) {
                    const diffMinutes = Math.floor(diffTime / (1000 * 60));
                    return diffMinutes <= 1 ? 'Expires in 1 minute' : `Expires in ${diffMinutes} minutes`;
                }
                return diffHours === 1 ? 'Expires in 1 hour' : `Expires in ${diffHours} hours`;
            } else if (diffDays < 7) {
                return diffDays === 1 ? 'Expires in 1 day' : `Expires in ${diffDays} days`;
            } else {
                const diffWeeks = Math.floor(diffDays / 7);
                if (diffWeeks < 4) {
                    return diffWeeks === 1 ? 'Expires in 1 week' : `Expires in ${diffWeeks} weeks`;
                } else {
                    return expirationDate.toLocaleDateString();
                }
            }
        };

        // Lifecycle
        onMounted(async () => {
            await loadConfig();
            await checkAuth();
            if (authenticated.value) {
                await loadFiles();
            }
        });

        // Return reactive state and methods
        return {
            // State
            authenticated,
            selectedFile,
            uploading,
            maxDownloads,
            expirationDays,
            uploadResult,
            files,
            fileInput,
            isDragging,
            appConfig,
            uploadProgress,
            uploadMessage,
            
            // Methods
            login,
            logout,
            fileSelected,
            handleDrop,
            upload,
            cancelUpload,
            loadFiles,
            deleteFile,
            copyUrl,
            copyShareUrl,
            downloadFile,
            formatFileSize,
            formatDate,
            
            // Globals
            window
        };
    }
}).mount('#app');