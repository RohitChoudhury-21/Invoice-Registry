// frontend/filters.js

export function getFilterParams() {
    // This gathers all values from your HTML inputs
    const params = {};
    
    // We map your HTML IDs to the parameter names your API expects
    const mapping = {
        'search': 'search',
        'vendor': 'vendor',
        'currency': 'currency',
        'dateFrom': 'date_from',
        'dateTo': 'date_to',
        'amountMin': 'amount_min',
        'amountMax': 'amount_max'
    };

    for (const [id, key] of Object.entries(mapping)) {
        const val = document.getElementById(id).value;
        if (val) params[key] = val;
    }

    return params;
}

export function resetFilters() {
    // Clears the HTML inputs
    ['search', 'vendor', 'currency', 'dateFrom', 'dateTo', 'amountMin', 'amountMax']
        .forEach(id => document.getElementById(id).value = '');
}
