<template>
    <div v-if="showStoredFiles" class="stored-files-container">
        <!-- Premium Background Layers (matching ToolsDrawer/SwarmDrawer architecture) -->
        <div class="bg-layer bg-hexgrid">
            <svg class="hexgrid-svg" viewBox="0 0 800 600" preserveAspectRatio="xMidYMid slice">
                <defs>
                    <pattern id="sfHexPattern" x="0" y="0" width="60" height="52" patternUnits="userSpaceOnUse">
                        <path class="hex-path" d="M30,0 L60,15 L60,37 L30,52 L0,37 L0,15 Z" fill="none" stroke-width="0.5"/>
                    </pattern>
                </defs>
                <rect width="100%" height="100%" fill="url(#sfHexPattern)"/>
                <!-- Animated connection lines -->
                <line v-for="i in 6" :key="'sfline-'+i" class="hex-connection"
                    :x1="80 + i * 110" :y1="60 + (i % 2) * 140"
                    :x2="180 + i * 110" :y2="140 + (i % 3) * 100"
                    :style="`animation-delay: ${i * 0.4}s`"/>
                <!-- Node points -->
                <circle v-for="i in 10" :key="'sfnode-'+i" class="hex-node"
                    :cx="50 + (i % 5) * 160" :cy="60 + Math.floor(i / 5) * 240" r="3"
                    :style="`animation-delay: ${i * 0.25}s`"/>
            </svg>
        </div>
        <div class="bg-layer bg-radial-glow"></div>
        <div class="bg-layer bg-data-streams">
            <span v-for="i in 5" :key="'sfstream-'+i" class="data-stream-particle" :style="`--delay: ${i * 0.8}s; --x-pos: ${12 + i * 18}%`"></span>
        </div>
        <div class="bg-layer bg-glow-orbs">
            <span class="glow-orb glow-orb-1"></span>
            <span class="glow-orb glow-orb-2"></span>
        </div>

        <!-- Premium Border System -->
        <div class="premium-border premium-border-top">
            <span class="border-pulse"></span>
        </div>
        <div class="premium-border premium-border-bottom"></div>
        <div class="premium-border premium-border-left"></div>
        <div class="premium-border premium-border-right"></div>

        <DialogHeader :icon="Database" :iconSize="32" :tooltipText="tooltipText" title="Stored Files"
            headerId="stored-files-header" @close="closeStoredFiles" />
        
        <div class="dialog-content">
            <div class="search-and-actions">
                <div class="search-wrapper">
                    <span class="p-input-icon-left">
                        <i class="pi pi-search" />
                        <InputText v-model="searchQuery" placeholder="Search files..." @input="onFilter" />
                    </span>
                </div>
                <div class="upload-btn-wrapper">
                    <Button @click="$refs.fileInput.click()" icon="pi pi-upload" class="p-button-primary upload-btn" label="Upload Files" />
                    <input multiple type="file" ref="fileInput" @change="uploadFile" class="hidden" />
                </div>
            </div>
            
            <DataTable ref="dt" :value="filteredFiles" 
                :rowHover="true"
                stripedRows 
                paginator 
                :rows="5" 
                :rowsPerPageOptions="[5, 10, 15]"
                tableStyle="min-width: 25rem" 
                class="files-table" 
                scrollable 
                scrollHeight="400px"
                paginatorTemplate="FirstPageLink PrevPageLink PageLinks NextPageLink LastPageLink RowsPerPageDropdown"
                currentPageReportTemplate="Showing {first} to {last} of {totalRecords} files">
                
                <Column field="fileId" hidden header="File ID" />
                
                <Column field="fileName" header="File" style="width: 50%">
                    <template #body="{ data }">
                        <div class="file-name-cell">
                            <div class="file-icon-wrapper">
                                <i :class="getFileIcon(data.fileType)" />
                            </div>
                            <div class="file-details">
                                <span class="file-name">{{ data.fileName }}</span>
                                <span class="file-size">{{ formatFileSize(data.fileSize) }}</span>
                            </div>
                        </div>
                    </template>
                </Column>
                
                <Column field="fileType" header="Format" style="width: 20%">
                    <template #body="{ data }">
                        <span class="file-format-badge">{{ getFileFormat(data.fileType) }}</span>
                    </template>
                </Column>
                
                <Column header="Actions" style="width: 30%">
                    <template #body="{ data }">
                        <div class="action-buttons">
                            <Button @click="downloadFile(data)" 
                                icon="pi pi-download" 
                                class="p-button-text p-button-rounded action-btn"
                                v-tooltip.top="'Download File'" />
                                
                            <Button @click.stop="addStoredFileToContext(data)" 
                                icon="pi pi-plus" 
                                class="p-button-text p-button-rounded action-btn action-btn-add"
                                v-tooltip.top="'Add to Context'" />
                                
                            <Button @click="handleDeleteFile(data.fileId)" 
                                icon="pi pi-trash" 
                                class="p-button-text p-button-rounded action-btn action-btn-delete"
                                v-tooltip.top="'Delete File'" />
                        </div>
                    </template>
                </Column>
                
                <template #empty>
                    <div class="empty-state">
                        <div class="empty-icon-wrapper">
                            <i class="pi pi-cloud-upload"></i>
                        </div>
                        <h3>No files found</h3>
                        <p>Upload files to see them here</p>
                        <Button @click="$refs.fileInput.click()" label="Upload Files" icon="pi pi-upload" class="p-button-outlined" />
                    </div>
                </template>
            </DataTable>
        </div>
    </div>
</template>

<script setup>
import { ref, onMounted, computed } from 'vue';
import DialogHeader from '../controls/DialogHeader.vue';
import { showStoredFiles, userText } from '@/libs/state-management/state';
import { addMessage } from '@/libs/conversation-management/message-processing';
import { saveMessagesHandler } from '@/libs/conversation-management/useConversations';
import { showToast } from '@/libs/utils/general-utils';
import { Upload, Database, FileText, Image as ImageIcon, FileJson } from 'lucide-vue-next';
import { storeFileData } from '@/libs/file-processing/image-analysis';
import InputText from 'primevue/inputtext';
import { fetchStoredFiles, deleteFile, getTotalDatabaseSize } from '@/libs/utils/indexed-db-utils';
import Button from 'primevue/button';
import Column from 'primevue/column';
import DataTable from 'primevue/datatable';

const files = ref([]);
const searchQuery = ref('');
const fileInput = ref(null);
const databaseSize = ref('0.00');

const updateDatabaseSize = async () => {
    databaseSize.value = await getTotalDatabaseSize();
};

const filteredFiles = computed(() => {
    if (!searchQuery.value) return files.value;
    return files.value.filter(file =>
        file.fileName.toLowerCase().includes(searchQuery.value.toLowerCase())
    );
});

const formatFileSize = (sizeInBytes) => {
    if (sizeInBytes < 1024) {
        return sizeInBytes + ' B';
    } else if (sizeInBytes < 1024 * 1024) {
        return (sizeInBytes / 1024).toFixed(2) + ' KB';
    } else {
        return (sizeInBytes / (1024 * 1024)).toFixed(2) + ' MB';
    }
};

const getFileIcon = (fileType) => {
    if (fileType.startsWith('image/')) {
        return 'pi pi-image';
    } else if (fileType === 'application/pdf') {
        return 'pi pi-file-pdf';
    } else if (fileType === 'application/json') {
        return 'pi pi-code';
    } else if (fileType.includes('text/')) {
        return 'pi pi-file-text';
    } else {
        return 'pi pi-file';
    }
};

const getFileFormat = (fileType) => {
    if (fileType.startsWith('image/')) {
        return fileType.split('/')[1].toUpperCase();
    } else if (fileType === 'application/pdf') {
        return 'PDF';
    } else if (fileType === 'application/json') {
        return 'JSON';
    } else if (fileType.includes('text/')) {
        return 'TEXT';
    } else {
        return fileType.split('/')[1] || 'FILE';
    }
};

const onFilter = () => {
    // The filtering is now handled by the computed property
};

const closeStoredFiles = () => {
    showStoredFiles.value = false;
};

const handleFetchStoredFiles = async () => {
    files.value = await fetchStoredFiles();
};

const addStoredFileToContext = async (file) => {
    const messageContent = file.fileType.startsWith('image/')
        ? [
            { type: 'image_url', image_url: { url: file.fileData } },
            { type: 'text', text: `${userText.value}\n\nImage: ${file.fileName}` }
        ]
        : [{ type: 'text', text: `${userText.value} ${file.fileData}` }];

    if (file.fileType.startsWith('image/')) {
        addMessage('user', messageContent);
    }
    else {
        addMessage('user', `#contextAdded: ${file.fileName} | ${messageContent[0].text}`);
    }

    addMessage('assistant', `${file.fileName} context added from storage.`);

    showToast("Successfully Added File Context From Storage");
    saveMessagesHandler();
    showStoredFiles.value = false;
};

const handleDeleteFile = async (fileId) => {
    try {
        await deleteFile(fileId);
        files.value = files.value.filter(file => file.fileId !== fileId);
        await updateDatabaseSize();
        showToast("File Deleted From Storage");
    } catch (error) {
        console.error('Failed to delete file:', error);
    }
};

const downloadFile = async (file) => {
    try {
        const blob = new Blob([file.fileData], { type: file.fileType });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = file.fileName;
        a.click();
        URL.revokeObjectURL(url);
        showToast('File downloaded successfully');
    } catch (error) {
        console.error('Error downloading file:', error);
        showToast('Failed to download file');
    }
};

const uploadFile = async (event) => {
    const selectedFiles = event.target.files;
    if (!selectedFiles.length) return;

    for (const file of selectedFiles) {
        await processFile(file);
    }

    await updateDatabaseSize();
};

const uploadDragDropFiles = async (files) => {
    if (!files.length) return;

    for (const file of files) {
        await processFile(file);

        await addStoredFileToContext(file);
    }

    await updateDatabaseSize();


};

const processFile = async (file) => {
    const reader = new FileReader();

    reader.onload = async (e) => {
        const contents = e.target.result;
        if (file.type.startsWith('image/')) {
            await storeFileData(file.name, contents, file.size, file.type);
        } else if (file.type === 'application/pdf') {
            await processPDF(contents, file);
        } else {
            await storeFileData(file.name, contents, file.size, file.type);
        }

        files.value = await fetchStoredFiles();
        console.log(files.value);

        showToast('File uploaded and stored successfully');
    };

    if (file.type.startsWith('image/')) {
        reader.readAsDataURL(file);
    } else if (file.type === 'application/pdf') {
        reader.readAsArrayBuffer(file);
    } else {
        reader.readAsText(file);
    }
};

const processPDF = async (contents, file) => {
    try {
        const loadingTask = pdfjsLib.getDocument({ data: contents });
        const pdfDoc = await loadingTask.promise;
        const numPages = pdfDoc.numPages;
        let pdfText = '';

        for (let i = 1; i <= numPages; i++) {
            const page = await pdfDoc.getPage(i);
            const textContent = await page.getTextContent();
            pdfText += textContent.items.map(item => item.str).join(' ') + '\n';
        }

        await storeFileData(file.name, pdfText, file.size, file.type);
    } catch (error) {
        console.error('Error parsing PDF:', error);
        showToast('Failed to parse PDF. It might be encrypted or corrupted.');
    }
};

const tooltipText = computed(() => `Total Browser Database Size: ${databaseSize.value}MB`);

onMounted(async () => {
    files.value = await fetchStoredFiles();
    await updateDatabaseSize();
});
</script>
<style scoped lang="scss">
// ============================================
// Main Container - Premium Glass Surface
// ============================================

.stored-files-container {
    position: fixed;
    z-index: 2000;
    padding: 0;
    color: var(--vera-text);
    border-radius: var(--vera-radius-xl, 18px);
    max-width: 850px;
    width: 82vw;
    max-height: 85vh;
    font-family: var(--vera-font-sans, 'Roboto', sans-serif);
    top: 50%;
    left: 50%;
    transform: translate(-50%, -50%);
    display: flex;
    flex-direction: column;
    overflow: hidden;
    transition: all 0.3s cubic-bezier(0.25, 0.8, 0.25, 1);

    // Premium glass surface
    background: var(--vera-panel-gradient);
    backdrop-filter: blur(20px);
    -webkit-backdrop-filter: blur(20px);

    // Premium border with gradient
    border: 1px solid transparent;
    background-clip: padding-box;

    // Layered shadow for depth
    box-shadow:
        0 0 0 1px var(--vera-accent-10),
        0 4px 30px rgba(var(--vera-shadow-rgb), 0.4),
        0 8px 60px rgba(var(--vera-shadow-rgb), 0.3),
        inset 0 1px 0 rgba(var(--vera-contrast-rgb), 0.05),
        inset 0 -1px 0 rgba(var(--vera-shadow-rgb), 0.2);

    // Content above background layers
    > *:not(.bg-layer):not(.premium-border) {
        position: relative;
        z-index: 10;
    }

    @media (max-width: 768px) {
        width: 95vw;
        max-height: 90vh;
    }
}

.dialog-content {
    padding: 0 1.5rem 1.5rem;
    flex: 1;
    display: flex;
    flex-direction: column;
    overflow: hidden;
}

.search-and-actions {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 1.5rem;
    gap: 1rem;

    @media (max-width: 600px) {
        flex-direction: column;
        align-items: stretch;
    }
}

.search-wrapper {
    flex: 1;
    
    .p-input-icon-left {
        width: 100%;
        position: relative;
        display: inline-flex;
        
        i {
            color: var(--vera-text-muted);
            position: absolute;
            left: 0.75rem;
            top: 50%;
            transform: translateY(-50%);
            z-index: 1;
        }

        input {
            width: 100%;
            background-color: var(--vera-panel-alt);
            border: 1px solid var(--vera-border);
            border-radius: 8px;
            padding: 0.7rem 1rem 0.7rem 2.5rem;
            transition: all 0.2s ease;
            color: var(--vera-text);
            
            &:focus {
                box-shadow: 0 0 0 3px var(--vera-accent-soft);
                background-color: var(--vera-panel-muted);
                border-color: var(--vera-accent);
            }
            
            &::placeholder {
                color: var(--vera-text-muted);
            }
        }
    }
}

.upload-btn-wrapper {
    .upload-btn {
        background: linear-gradient(45deg, var(--vera-accent), var(--vera-accent-strong));
        border: none;
        border-radius: 8px;
        padding: 0.7rem 1.2rem;
        transition: all 0.3s ease;
        box-shadow: 0 2px 5px rgba(var(--vera-shadow-rgb), 0.2);
        
        &:hover {
            background: linear-gradient(45deg, var(--vera-accent-strong), var(--vera-accent));
            transform: translateY(-2px);
            box-shadow: 0 4px 8px rgba(var(--vera-shadow-rgb), 0.3);
        }
        
        &:active {
            transform: translateY(0);
        }
    }
}

.files-table {
    border-radius: var(--vera-radius-md, 12px);
    overflow: hidden;
    box-shadow: var(--vera-panel-shadow);
    flex: 1;
    display: flex;
    flex-direction: column;
    background-color: var(--vera-dialog-content-bg);
    border: 1px solid var(--vera-border);

    :deep(.p-datatable) {
        display: flex;
        flex-direction: column;
        flex: 1;
        overflow: hidden;
    }

    :deep(.p-datatable-wrapper) {
        flex: 1;
        overflow: hidden;
    }

    :deep(.p-datatable-header) {
        background-color: color-mix(in srgb, var(--vera-panel-muted) 50%, transparent);
        padding: 1rem;
        border-bottom: 1px solid var(--vera-border);
    }

    :deep(.p-datatable-thead) th {
        background-color: color-mix(in srgb, var(--vera-panel-muted) 70%, transparent);
        color: var(--vera-text);
        font-weight: 500;
        border-color: var(--vera-border);
        padding: 1rem;
        position: sticky;
        top: 0;
        z-index: 1;
        font-size: 0.9rem;
        letter-spacing: 0.5px;
        text-transform: uppercase;
    }

    :deep(.p-datatable-tbody) td {
        padding: 0.8rem 1rem;
        border-color: var(--vera-border);
    }

    :deep(.p-datatable-tbody) tr {
        transition: background-color 0.2s ease;
        backdrop-filter: blur(5px);

        &:nth-child(odd) {
            background-color: var(--vera-glass-bg);
        }

        &:hover {
            background-color: var(--vera-accent-faint) !important;
        }

        &.p-highlight {
            background-color: var(--vera-accent-soft) !important;
        }
    }

    :deep(.p-paginator) {
        background-color: color-mix(in srgb, var(--vera-panel-muted) 50%, transparent);
        border-top: 1px solid var(--vera-border);
        padding: 0.75rem;

        button {
            color: var(--vera-text-muted);

            &:hover {
                background-color: var(--vera-accent-faint);
            }

            &.p-highlight {
                background-color: var(--vera-accent);
            }
        }
    }
}

.file-name-cell {
    display: flex;
    align-items: center;
    gap: 1rem;

    .file-icon-wrapper {
        width: 36px;
        height: 36px;
        display: flex;
        align-items: center;
        justify-content: center;
        background-color: var(--vera-accent-faint);
        border-radius: var(--vera-radius-sm, 8px);

        i {
            font-size: 1.3rem;
            color: var(--vera-accent);
        }
    }

    .file-details {
        display: flex;
        flex-direction: column;

        .file-name {
            font-weight: 500;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
            color: var(--vera-text);
        }

        .file-size {
            font-size: 0.8rem;
            color: var(--vera-text-muted);
            margin-top: 0.25rem;
        }
    }
}

.file-format-badge {
    display: inline-block;
    padding: 0.25rem 0.75rem;
    background-color: var(--vera-accent-faint);
    color: var(--vera-accent);
    border-radius: 30px;
    font-size: 0.75rem;
    font-weight: 600;
    letter-spacing: 0.5px;
    text-transform: uppercase;
}

.action-buttons {
    display: flex;
    gap: 0.25rem;
    justify-content: flex-end;

    .action-btn {
        width: 2.2rem;
        height: 2.2rem;
        transition: all 0.2s ease;
        color: var(--vera-text-muted);
        background-color: transparent;
        border: none;

        &:hover {
            background-color: var(--vera-accent-faint);
            color: var(--vera-text);
            transform: translateY(-2px);
        }

        &.action-btn-add:hover {
            color: var(--vera-success);
        }

        &.action-btn-delete:hover {
            color: var(--vera-danger);
        }
    }
}

.empty-state {
    display: flex;
    flex-direction: column;
    align-items: center;
    padding: 4rem 1rem;
    text-align: center;
    
    .empty-icon-wrapper {
        width: 80px;
        height: 80px;
        border-radius: 50%;
        background-color: var(--vera-accent-faint);
        display: flex;
        align-items: center;
        justify-content: center;
        margin-bottom: 1.5rem;
        
        i {
            font-size: 2.5rem;
            color: var(--vera-accent);
        }
    }
    
    h3 {
        margin: 0 0 0.5rem 0;
        font-weight: 500;
        color: var(--vera-text);
    }

    p {
        margin: 0 0 2rem 0;
        color: var(--vera-text-muted);
    }
    
    button {
        background-color: transparent;
        border: 2px solid var(--vera-accent);
        color: var(--vera-accent);
        border-radius: 8px;
        padding: 0.5rem 1.5rem;
        transition: all 0.3s ease;
        
        &:hover {
            background-color: var(--vera-accent);
            color: var(--primary-color-text);
        }
    }
}

.hidden {
    display: none;
}

// ============================================
// VERA Stored Files Dialog - Nixie Tube Aesthetic
// Warm amber/copper tones to match the rest of UI
// ============================================

$secondary-accent-rgb: var(--vera-warning-rgb);
$secondary-accent-soft: rgba(var(--vera-warning-rgb), 0.6);


// ============================================
// Background Layer System
// ============================================

.bg-layer {
    position: absolute;
    inset: 0;
    pointer-events: none;
    overflow: hidden;
}

// Layer 1: Hexagonal Grid Pattern
.bg-hexgrid {
    z-index: 1;
    opacity: 0.35;

    .hexgrid-svg {
        width: 100%;
        height: 100%;
    }

    .hex-path {
        stroke: var(--vera-accent-soft);
        opacity: 0.25;
    }

    .hex-connection {
        stroke: var(--vera-accent);
        stroke-width: 1;
        stroke-dasharray: 60;
        stroke-dashoffset: 60;
        opacity: 0.35;
        animation: hexTrace calc(6s / var(--vera-anim-speed, 1)) ease-in-out infinite;
    }

    .hex-node {
        fill: var(--vera-accent);
        filter: drop-shadow(0 0 4px var(--vera-accent));
        animation: hexNodePulse calc(3s / var(--vera-anim-speed, 1)) ease-in-out infinite;
    }
}

// Layer 2: Radial Glow Background
.bg-radial-glow {
    z-index: 2;
    background:
        radial-gradient(ellipse at 20% 15%, var(--vera-accent-soft) 0%, transparent 45%),
        radial-gradient(ellipse at 80% 85%, rgba($secondary-accent-rgb, 0.12) 0%, transparent 40%);
    animation: radialDrift calc(18s / var(--vera-anim-speed, 1)) ease-in-out infinite;
}

// Layer 3: Data Stream Particles
.bg-data-streams {
    z-index: 3;

    .data-stream-particle {
        position: absolute;
        width: 2px;
        height: 18px;
        background: linear-gradient(180deg, var(--vera-accent), transparent);
        border-radius: 2px;
        left: var(--x-pos, 50%);
        top: -25px;
        opacity: 0;
        animation: dataStreamFall calc(5s / var(--vera-anim-speed, 1)) linear infinite;
        animation-delay: var(--delay, 0s);
    }
}

// Layer 4: Ambient Glow Orbs
.bg-glow-orbs {
    z-index: 4;

    .glow-orb {
        position: absolute;
        border-radius: 50%;
        filter: blur(70px);

        &.glow-orb-1 {
            width: 250px;
            height: 250px;
            top: -50px;
            right: -60px;
            background: radial-gradient(circle, var(--vera-accent-soft) 0%, transparent 70%);
            opacity: 0.3;
            animation: orbFloat calc(8s / var(--vera-anim-speed, 1)) ease-in-out infinite;
        }

        &.glow-orb-2 {
            width: 180px;
            height: 180px;
            bottom: -30px;
            left: -40px;
            background: radial-gradient(circle, rgba($secondary-accent-rgb, 0.35) 0%, transparent 70%);
            opacity: 0.25;
            animation: orbFloat calc(10s / var(--vera-anim-speed, 1)) ease-in-out infinite 3s;
        }
    }
}

// ============================================
// Premium Border System
// ============================================

.premium-border {
    position: absolute;
    pointer-events: none;
    z-index: 100;

    &.premium-border-top {
        top: 0;
        left: 0;
        right: 0;
        height: 2px;
        background: linear-gradient(
            90deg,
            transparent 0%,
            var(--vera-accent-soft) 10%,
            var(--vera-accent) 50%,
            var(--vera-accent-soft) 90%,
            transparent 100%
        );
        box-shadow:
            0 0 20px var(--vera-accent-soft),
            0 2px 25px var(--vera-accent-25);

        .border-pulse {
            position: absolute;
            top: 0;
            left: -120px;
            width: 120px;
            height: 2px;
            background: linear-gradient(90deg, transparent, rgba(var(--vera-contrast-rgb),0.8), var(--vera-accent), transparent);
            animation: borderSweep calc(4s / var(--vera-anim-speed, 1)) linear infinite;
        }
    }

    &.premium-border-bottom {
        bottom: 0;
        left: 0;
        right: 0;
        height: 2px;
        background: linear-gradient(
            90deg,
            transparent 0%,
            $secondary-accent-soft 15%,
            rgba($secondary-accent-rgb, 1) 50%,
            $secondary-accent-soft 85%,
            transparent 100%
        );
        box-shadow:
            0 0 18px $secondary-accent-soft,
            0 -2px 25px rgba($secondary-accent-rgb, 0.15);
        animation: borderGlow calc(4s / var(--vera-anim-speed, 1)) ease-in-out infinite;
    }

    &.premium-border-left {
        top: 50px;
        bottom: 50px;
        left: 0;
        width: 2px;
        background: linear-gradient(
            180deg,
            transparent 0%,
            var(--vera-accent-soft) 20%,
            var(--vera-accent) 50%,
            var(--vera-accent-soft) 80%,
            transparent 100%
        );
        box-shadow: 2px 0 18px var(--vera-accent-soft);
        opacity: 0.5;
        animation: verticalGlow calc(5s / var(--vera-anim-speed, 1)) ease-in-out infinite;
    }

    &.premium-border-right {
        top: 50px;
        bottom: 50px;
        right: 0;
        width: 2px;
        background: linear-gradient(
            180deg,
            transparent 0%,
            rgba($secondary-accent-rgb, 0.4) 20%,
            $secondary-accent-soft 50%,
            rgba($secondary-accent-rgb, 0.4) 80%,
            transparent 100%
        );
        box-shadow: -2px 0 18px rgba($secondary-accent-rgb, 0.25);
        opacity: 0.4;
        animation: verticalGlow calc(5s / var(--vera-anim-speed, 1)) ease-in-out infinite 2s;
    }
}

// ============================================
// Premium Keyframe Animations
// ============================================

@keyframes hexTrace {
    0% {
        stroke-dashoffset: 60;
        opacity: 0.15;
    }
    50% {
        stroke-dashoffset: 0;
        opacity: 0.5;
    }
    100% {
        stroke-dashoffset: -60;
        opacity: 0.15;
    }
}

@keyframes hexNodePulse {
    0%, 100% {
        r: 3;
        filter: drop-shadow(0 0 3px var(--vera-accent-soft));
    }
    50% {
        r: 4;
        filter: drop-shadow(0 0 8px var(--vera-accent));
    }
}

@keyframes radialDrift {
    0%, 100% {
        opacity: 0.75;
        transform: scale(1) translate(0, 0);
    }
    33% {
        opacity: 0.95;
        transform: scale(1.03) translate(8px, -8px);
    }
    66% {
        opacity: 0.85;
        transform: scale(0.98) translate(-5px, 5px);
    }
}

@keyframes dataStreamFall {
    0% {
        top: -25px;
        opacity: 0;
    }
    10% {
        opacity: 0.65;
    }
    90% {
        opacity: 0.45;
    }
    100% {
        top: 100%;
        opacity: 0;
    }
}

@keyframes orbFloat {
    0%, 100% {
        transform: translate(0, 0) scale(1);
        opacity: 0.25;
    }
    25% {
        transform: translate(12px, -8px) scale(1.03);
        opacity: 0.35;
    }
    50% {
        transform: translate(-8px, 12px) scale(0.97);
        opacity: 0.3;
    }
    75% {
        transform: translate(-12px, -4px) scale(1.01);
        opacity: 0.32;
    }
}

@keyframes borderSweep {
    0% {
        left: -120px;
        opacity: 0;
    }
    10% {
        opacity: 1;
    }
    90% {
        opacity: 1;
    }
    100% {
        left: 100%;
        opacity: 0;
    }
}

@keyframes borderGlow {
    0%, 100% {
        opacity: 0.45;
        box-shadow: 0 0 12px $secondary-accent-soft;
    }
    50% {
        opacity: 0.75;
        box-shadow: 0 0 22px rgba($secondary-accent-rgb, 1);
    }
}

@keyframes verticalGlow {
    0%, 100% {
        opacity: 0.35;
    }
    50% {
        opacity: 0.65;
    }
}

// ============================================
// Reduced Motion & Lite Mode Support
// ============================================

@media (prefers-reduced-motion: reduce) {
    .bg-layer,
    .premium-border,
    .hex-connection,
    .hex-node,
    .data-stream-particle,
    .glow-orb,
    .border-pulse {
        animation: none !important;
    }

    .bg-hexgrid { opacity: 0.15; }
    .bg-radial-glow { opacity: 0.4; }
    .glow-orb { opacity: 0.15; }
    .premium-border { opacity: 0.5; }
}

/* Custom scrollbar styling */
:deep(.p-datatable-wrapper),
:deep(.p-datatable-scrollable-body),
:deep(.p-dropdown-items-wrapper) {
    /* Firefox */
    scrollbar-width: thin;
    scrollbar-color: var(--vera-accent-soft) rgba(var(--vera-shadow-rgb), 0.2);

    /* Chrome, Edge, Safari */
    &::-webkit-scrollbar {
        width: 8px;
        height: 8px;
    }

    &::-webkit-scrollbar-track {
        background: rgba(var(--vera-shadow-rgb), 0.2);
        border-radius: 4px;
    }

    &::-webkit-scrollbar-thumb {
        background: var(--vera-accent-soft);
        border-radius: 4px;
        transition: background 0.2s ease;

        &:hover {
            background: var(--vera-accent);
        }
    }
}
</style>
