import { fetchInvoices, uploadDocument } from './api.js';
import { renderInvoiceTable } from './table.js';
import { getFilterParams, resetFilters } from './filters.js';
import { setupPagination, updatePaginationUI } from './pagination.js';

// ==========================
// CONFIGURATION
// ==========================
let currentPage = 1;
let pageSize = 20;

document.addEventListener("DOMContentLoaded", async () => {
    initializeEvents();
    loadDocuments();
    loadInvoices();
    loadDuplicates();
    setupPagination((direction) => {
        if (direction === 'prev' && currentPage > 1) {
            currentPage--;
        } else if (direction === 'next') {
            currentPage++;
        }
        loadInvoices();
    });
});

function initializeEvents() {
    document.getElementById("uploadForm").addEventListener("submit", uploadPDF);
    document.getElementById("applyFilters").addEventListener("click", () => {
        currentPage = 1; // Always reset to page 1 when filtering
        loadInvoices();
    });
    document.getElementById("resetFilters").addEventListener("click", () => {
        resetFilters(); // This clears the inputs (from filters.js)
        loadInvoices(); // Reload the default list
    });
    document.getElementById("exportBtn").addEventListener("click", exportCSV);
}

// ==========================
// ACTIONS
// ==========================

async function uploadPDF(event) {
    event.preventDefault();
    const fileInput = document.getElementById("pdfFile");
    
    if (fileInput.files.length === 0) return alert("Please choose a PDF.");

    try {
        const file = fileInput.files[0];
        const result = await uploadDocument(file);
        
        document.getElementById("uploadResult").innerHTML = `
            <strong style="color: green;">✓ Upload Successful</strong><br>
            Status: ${result.status}<br>
            Document ID: ${result.document_id}
        `;
        
        fileInput.value = "";  // Clear the input
        loadDocuments();
        loadInvoices();
        loadDuplicates();
        
    } catch (error) {
        // Handle 409 duplicates
        if (error.message.includes("409") || error.message.includes("Duplicate")) {
            document.getElementById("uploadResult").innerHTML = `
                <strong style="color: orange;">⚠ Duplicate Detected</strong><br>
                ${error.message}
            `;
        } else {
            document.getElementById("uploadResult").innerHTML = `
                <strong style="color: red;">✗ Upload Failed</strong><br>
                ${error.message}
            `;
        }
        console.error("Upload error:", error);
    }
}

async function loadInvoices() {
    const offset = (currentPage - 1) * pageSize;
    const filters = getFilterParams();
    const data = await fetchInvoices({ limit: pageSize, offset: offset, ...filters });

    if (!data.invoices) {
        console.error(data);
        return;
    }
    
    renderInvoiceTable(data.invoices);
    updatePaginationUI(currentPage, data.total, pageSize);
}

function exportCSV() {
    const filters = getFilterParams();

    const params = new URLSearchParams({
        format: "csv",
        ...filters
    });

    window.location.href =
        `http://127.0.0.1:8000/export?${params.toString()}`;
}

// You can move this logic to a separate file later if you want
async function loadDocuments() {
    try {
        const response = await fetch("http://127.0.0.1:8000/documents");

        if (!response.ok) {
            throw new Error(`HTTP error! Status: ${response.status}`);
        }

        const data = await response.json();

        console.log("DEBUG - Documents data received:", data);

        const tbody = document.getElementById("documentsTableBody");
        if (!tbody) return;

        tbody.innerHTML = "";

        const docList = Array.isArray(data)
            ? data
            : (data.documents || []);

        if (docList.length > 0) {
            docList.forEach(doc => {
                tbody.innerHTML += `
                <tr>
                    <td>${doc.id}</td>
                    <td>${doc.filename}</td>
                    <td>${doc.status}</td>
                    <td>${doc.doc_type || "N/A"}</td>
                    <td>${doc.uploaded_at}</td>
                </tr>`;
            });
        } else {
            console.warn("No documents found.");
        }
    }
    catch (err) {
        console.error("Failed to load documents:", err);
    }
}

async function loadDuplicates() {
    try {
        const response = await fetch("http://127.0.0.1:8000/duplicates");
        const duplicates = await response.json();

        const table = document.getElementById("duplicateTable");
        const tbody = document.getElementById("duplicateTableBody");
        const noMsg = document.getElementById("noDuplicatesMessage");

        if (!duplicates || duplicates.length === 0) {
            table.style.display = "none";
            noMsg.style.display = "block";
            return;
        }

        table.style.display = "table";
        noMsg.style.display = "none";
        tbody.innerHTML = "";

        for (const dup of duplicates) {
            const row = document.createElement("tr");
            row.innerHTML = `
                <td>${dup.invoice1_id}</td>
                <td id="inv1-${dup.id}">Loading...</td>
                <td>${dup.invoice2_id}</td>
                <td id="inv2-${dup.id}">Loading...</td>
                <td>${dup.match_type || "unknown"}</td>
                <td>${(dup.score ?? 0).toFixed(2)}</td>
                <td>
                    <button class="merge-btn" data-id="${dup.id}" data-inv1="${dup.invoice1_id}" data-inv2="${dup.invoice2_id}">Merge</button>
                    <button class="not-duplicate-btn" data-id="${dup.id}">Not Duplicate</button>
                </td>
            `;
            tbody.appendChild(row);

            fetch(`http://127.0.0.1:8000/invoices/${dup.invoice1_id}`)
                .then(r => r.json())
                .then(inv => {
                    document.getElementById(`inv1-${dup.id}`).innerText = 
                        `${inv.invoice_number} (${inv.vendor_name})`;
                })
                .catch(() => {
                    document.getElementById(`inv1-${dup.id}`).innerText = "Error loading";
                });

            fetch(`http://127.0.0.1:8000/invoices/${dup.invoice2_id}`)
                .then(r => r.json())
                .then(inv => {
                    document.getElementById(`inv2-${dup.id}`).innerText = 
                        `${inv.invoice_number} (${inv.vendor_name})`;
                })
                .catch(() => {
                    document.getElementById(`inv2-${dup.id}`).innerText = "Error loading";
                });
        }

        document.querySelectorAll(".merge-btn").forEach(btn => {
            btn.addEventListener("click", async (e) => {
                const candidateId = e.target.getAttribute("data-id");
                const inv1 = e.target.getAttribute("data-inv1");
                const inv2 = e.target.getAttribute("data-inv2");
                
                if (confirm(`Merge invoice ${inv2} into ${inv1}?`)) {
                    try {
                        const res = await fetch(`http://127.0.0.1:8000/duplicates/${candidateId}/merge`, {
                            method: "POST"
                        });
                        if (res.ok) {
                            alert("Merged successfully!");
                            loadDuplicates();
                        } else {
                            alert("Merge failed");
                        }
                    } catch (err) {
                        alert("Error merging: " + err.message);
                    }
                }
            });
        });

        document.querySelectorAll(".not-duplicate-btn").forEach(btn => {
            btn.addEventListener("click", async (e) => {
                const candidateId = e.target.getAttribute("data-id");
                
                try {
                    const res = await fetch(`http://127.0.0.1:8000/duplicates/${candidateId}/dismiss`, {
                        method: "POST"
                    });
                    if (res.ok) {
                        alert("Marked as not a duplicate");
                        loadDuplicates();
                    } else {
                        alert("Failed to dismiss");
                    }
                } catch (err) {
                    alert("Error: " + err.message);
                }
            });
        });

    } catch (error) {
        console.error("Error loading duplicates:", error);
    }
}