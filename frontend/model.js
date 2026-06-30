import { API_BASE, updateInvoiceStatus as apiUpdateInvoiceStatus } from './api.js';

export async function openInvoiceModal(invoiceId) {
    try {
        // 1. Fetch the specific invoice details
        const response = await fetch(`${API_BASE}/invoices/${invoiceId}`);
        if (!response.ok) throw new Error("Failed to fetch invoice details");
        
        const invoice = await response.json();
        
        // 2. Find or create the modal container in your HTML
        let modal = document.getElementById("invoiceModal");
        if (!modal) {
            modal = document.createElement("div");
            modal.id = "invoiceModal";
            modal.className = "modal"; // Make sure you have basic CSS for this class
            document.body.appendChild(modal);
        }

        // 3. Inject the HTML for the popup
        modal.innerHTML = `
            <div class="modal-content" style="background: white; padding: 20px; border: 1px solid #ccc; position: fixed; top: 20%; left: 30%; width: 40%; z-index: 1000; box-shadow: 0px 4px 6px rgba(0,0,0,0.1);">
                <h2>Invoice Details: ${invoice.invoice_number}</h2>
                <p><strong>Vendor:</strong> ${invoice.vendor_name}</p>
                <p><strong>Date:</strong> ${invoice.invoice_date}</p>
                <p><strong>Amount:</strong> ${invoice.total_amount} ${invoice.currency}</p>
                <p><strong>Status:</strong> ${invoice.review_status}</p>
                
                <hr>
                
                <button onclick="updateInvoiceStatus(${invoice.id}, 'approved')" style="background: green; color: white;">Approve</button>
                <button onclick="updateInvoiceStatus(${invoice.id}, 'rejected')" style="background: red; color: white;">Reject</button>
                <button onclick="closeModal()" style="margin-left: 20px;">Close</button>
            </div>
        `;
        
        modal.style.display = "block";
    } catch (error) {
        console.error(error);
        alert("Could not load invoice details.");
    }
}

// Helper to close the modal
window.closeModal = function() {
    const modal = document.getElementById("invoiceModal");
    if (modal) modal.style.display = "none";
}

// Helper to update status (calls your backend)
window.updateInvoiceStatus = async function(id, status) {
    try {
        const result = await apiUpdateInvoiceStatus(id, status);
        alert(`Status updated to: ${result.new_status}`);
        closeModal();
    } catch (error) {
        alert("Failed to update status.");
        console.error(error);
    }
}