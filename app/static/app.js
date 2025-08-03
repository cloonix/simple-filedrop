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
            
            uploading.value = true;
            const formData = new FormData();
            formData.append('file', selectedFile.value);
            
            if (maxDownloads.value) {
                formData.append('max_downloads', maxDownloads.value);
            }
            formData.append('expiration_days', expirationDays.value);

            try {
                const response = await fetch('/api/upload', {
                    method: 'POST',
                    body: formData
                });
                
                if (response.ok) {
                    uploadResult.value = await response.json();
                    
                    // Reset form
                    fileInput.value.value = '';
                    selectedFile.value = null;
                    maxDownloads.value = null;
                    
                    // Refresh file list
                    await loadFiles();
                } else {
                    console.error('Upload failed:', response.statusText);
                }
            } catch (error) {
                console.error('Upload error:', error);
            } finally {
                uploading.value = false;
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

        const formatFileSize = (bytes) => {
            if (bytes === 0) return '0 Bytes';
            
            const k = 1024;
            const sizes = ['Bytes', 'KB', 'MB', 'GB', 'TB'];
            const i = Math.floor(Math.log(bytes) / Math.log(k));
            
            return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
        };

        const formatDate = (dateString) => {
            const date = new Date(dateString);
            const now = new Date();
            const diffTime = Math.abs(now - date);
            const diffDays = Math.ceil(diffTime / (1000 * 60 * 60 * 24));
            
            if (diffDays <= 1) {
                return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
            } else if (diffDays <= 7) {
                return `${diffDays} days ago`;
            } else {
                return date.toLocaleDateString();
            }
        };

        // Lifecycle
        onMounted(async () => {
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
            
            // Methods
            login,
            logout,
            fileSelected,
            handleDrop,
            upload,
            loadFiles,
            deleteFile,
            copyUrl,
            copyShareUrl,
            formatFileSize,
            formatDate,
            
            // Globals
            window
        };
    }
}).mount('#app');