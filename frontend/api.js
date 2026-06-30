// frontend/api.js

export const API_BASE = "http://127.0.0.1:8000";

// Fetch paginated invoices with optional filters
export async function fetchInvoices(params = {}) {
    const query = new URLSearchParams(params).toString();
    const response = await fetch(`${API_BASE}/invoices?${query}`);
    return await response.json();
}

// Fetch a single invoice by ID
export async function fetchInvoiceDetail(id) {
    const response = await fetch(`${API_BASE}/invoices/${id}`);
    if (!response.ok) {
        const error = await response.json();
        throw new Error(
            error.detail || error.message || `HTTP ${response.status}`
        );
    }
    return await response.json();
}

// Delete an invoice (Soft delete)
export async function deleteInvoice(id) {
    const response = await fetch(`${API_BASE}/invoices/${id}`, {
        method: 'DELETE'
    });
    return await response.json();
}

// Upload a new PDF document
export async function uploadDocument(file) {
    const formData = new FormData();
    formData.append("file", file);
    
    const response = await fetch(`${API_BASE}/upload`, {
        method: "POST",
        body: formData
    });

    const result = await response.json();
console.log("UPLOAD RESPONSE:", result);

if (!response.ok) {
    let errorMessage = "Upload failed";

    if (typeof result.detail === "string") {
        errorMessage = result.detail;
    }
    else if (typeof result.detail === "object") {
        errorMessage = JSON.stringify(result.detail);
    }
    else if (typeof result.message === "string") {
        errorMessage = result.message;
    }

    throw new Error(errorMessage);
}

return result;
}

// Get system stats
export async function fetchStats() {
    const response = await fetch(`${API_BASE}/stats`);
    return await response.json();
}

// Update Invoice Status
export async function updateInvoiceStatus(id, status) {
    const response = await fetch(`${API_BASE}/invoices/${id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ review_status: status })
    });
    
    if (!response.ok) throw new Error("Failed to update status");
    return await response.json();
}