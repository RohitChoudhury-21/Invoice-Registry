import { openInvoiceModal } from './model.js';
import { updateInvoiceStatus, deleteInvoice } from './api.js'; // <-- NEW: Imported deleteInvoice

export function renderInvoiceTable(invoices) {
    const tbody = document.getElementById("invoiceTableBody");
    if (!tbody) return;
    
    tbody.innerHTML = "";

    invoices.forEach(invoice => {
        const row = document.createElement("tr");
        
        let statusColor = "black";
        if (invoice.review_status === "approved") statusColor = "green";
        if (invoice.review_status === "rejected") statusColor = "red";

        row.innerHTML = `
            <td>${invoice.id}</td>
            <td>${invoice.invoice_number}</td>
            <td>${invoice.vendor_name}</td>
            <td>${invoice.invoice_date ?? ""}</td>
            <td>${invoice.total_amount ?? ""}</td>
            <td>${invoice.currency ?? ""}</td>
            <td style="color: ${statusColor}; font-weight: bold;" class="status-cell">${invoice.review_status}</td>
            <td>
                <button class="view-btn" data-id="${invoice.id}">View</button>
                <button class="approve-btn" data-id="${invoice.id}">Approve</button>
                <button class="reject-btn" data-id="${invoice.id}">Reject</button>
                <button class="archive-btn" data-id="${invoice.id}">Archive</button>
            </td>
        `;
        tbody.appendChild(row);
    });

    // 1. View Button Logic
    document.querySelectorAll('.view-btn').forEach(button => {
        button.addEventListener('click', (e) => {
            const invoiceId = e.target.getAttribute('data-id');
            openInvoiceModal(invoiceId);
        });
    });

    // 2. Approve Button Logic
    document.querySelectorAll('.approve-btn').forEach(button => {
        button.addEventListener('click', async (e) => {
            const invoiceId = e.target.getAttribute('data-id');
            try {
                const result = await updateInvoiceStatus(invoiceId, "approved");
                const statusCell = e.target.closest('tr').querySelector('.status-cell');
                statusCell.innerText = result.review_status;
                statusCell.style.color = "green";
            } catch (error) {
                alert("Failed to approve invoice.");
                console.error(error);
            }
        });
    });

    // 3. Reject Button Logic
    document.querySelectorAll('.reject-btn').forEach(button => {
        button.addEventListener('click', async (e) => {
            const invoiceId = e.target.getAttribute('data-id');
            try {
                const result = await updateInvoiceStatus(invoiceId, "rejected");
                const statusCell = e.target.closest('tr').querySelector('.status-cell');
                statusCell.innerText = result.review_status;
                statusCell.style.color = "red";
            } catch (error) {
                alert("Failed to reject invoice.");
                console.error(error);
            }
        });
    });

    // 4. Archive Button Logic (NEW)
    document.querySelectorAll('.archive-btn').forEach(button => {
        button.addEventListener('click', async (e) => {
            const invoiceId = e.target.getAttribute('data-id');
            
            // Add a safety check so users don't accidentally delete things
            if(confirm("Are you sure you want to archive this invoice?")) {
                try {
                    const result = await deleteInvoice(invoiceId);

                    if (result) {
                        e.target.closest('tr').remove();
                    }
                } catch (error) {
                    alert("Failed to archive invoice.");
                    console.error(error);
                }
            }
        });
    });
}