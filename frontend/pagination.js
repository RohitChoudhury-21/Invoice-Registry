// frontend/pagination.js

export function setupPagination(onPageChange) {
    // Using your specific IDs: previousPage and nextPage
    document.getElementById("previousPage").addEventListener("click", () => {
        onPageChange('prev');
    });
    document.getElementById("nextPage").addEventListener("click", () => {
        onPageChange('next');
    });
}

export function updatePaginationUI(currentPage, total, pageSize) {
    const totalPages = Math.ceil(total / pageSize) || 1;
    
    // Using your specific ID: pageInfo
    document.getElementById("pageInfo").innerText = `Page ${currentPage} of ${totalPages}`;
    
    // Disable/Enable buttons
    document.getElementById("previousPage").disabled = currentPage === 1;
    document.getElementById("nextPage").disabled = currentPage >= totalPages;
}