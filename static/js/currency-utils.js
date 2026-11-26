/**
 * Currency Utilities for Multi-Purpose App
 * Handles currency updates and formatting across all pages
 */

class CurrencyManager {
    constructor() {
        this.currentCurrency = {
            code: 'USD',
            symbol: '$'
        };
        this.listeners = [];
        this.init();
    }

    init() {
        // Get current currency from page data or localStorage
        this.loadCurrentCurrency();
        
        // Listen for currency update events
        window.addEventListener('currencyUpdated', (event) => {
            this.handleCurrencyUpdate(event.detail);
        });
        
        // Listen for storage changes (for cross-tab updates)
        window.addEventListener('storage', (event) => {
            if (event.key === 'app_currency') {
                this.handleCurrencyUpdate(JSON.parse(event.newValue));
            }
        });
    }

    loadCurrentCurrency() {
        // Try to get from page data (meta tag)
        const currencyData = document.querySelector('meta[name="currency-data"]');
        if (currencyData) {
            try {
                const data = JSON.parse(currencyData.getAttribute('content'));
                this.currentCurrency = {
                    code: data.code || 'USD',
                    symbol: data.symbol || '$'
                };
                // Store in localStorage
                localStorage.setItem('user_currency_symbol', this.currentCurrency.symbol);
                localStorage.setItem('user_currency_code', this.currentCurrency.code);
                localStorage.setItem('app_currency', JSON.stringify(this.currentCurrency));
                return;
            } catch (e) {
                console.warn('Failed to parse currency data from meta tag');
            }
        }
        
        // Try to get from data attributes on currency symbols
        const currencySymbolElement = document.querySelector('.currency-symbol[data-symbol]');
        if (currencySymbolElement) {
            const symbol = currencySymbolElement.getAttribute('data-symbol');
            if (symbol) {
                this.currentCurrency.symbol = symbol;
                localStorage.setItem('user_currency_symbol', symbol);
            }
        }
        
        // Fallback to localStorage
        const stored = localStorage.getItem('app_currency');
        if (stored) {
            try {
                this.currentCurrency = JSON.parse(stored);
            } catch (e) {
                console.warn('Failed to parse stored currency data');
            }
        }
        
        // Final fallback: check simple localStorage keys
        const storedSymbol = localStorage.getItem('user_currency_symbol');
        const storedCode = localStorage.getItem('user_currency_code');
        if (storedSymbol || storedCode) {
            this.currentCurrency = {
                code: storedCode || this.currentCurrency.code,
                symbol: storedSymbol || this.currentCurrency.symbol
            };
        }
    }

    handleCurrencyUpdate(currencyInfo) {
        const oldCurrency = { ...this.currentCurrency };
        this.currentCurrency = {
            code: currencyInfo.currencyCode || currencyInfo.code,
            symbol: currencyInfo.currencySymbol || currencyInfo.symbol
        };

        // Store in localStorage (both formats for compatibility)
        localStorage.setItem('app_currency', JSON.stringify(this.currentCurrency));
        localStorage.setItem('user_currency_symbol', this.currentCurrency.symbol);
        localStorage.setItem('user_currency_code', this.currentCurrency.code);

        // Notify all listeners
        this.notifyListeners(oldCurrency, this.currentCurrency);

        // Update all currency displays on the page
        this.updateCurrencyDisplays();
        
        // Dispatch custom event for other listeners
        document.dispatchEvent(new CustomEvent('currencyChanged', {
            detail: { symbol: this.currentCurrency.symbol, code: this.currentCurrency.code }
        }));
    }

    updateCurrencyDisplays() {
        // Update all standalone currency symbols
        document.querySelectorAll('.currency-symbol').forEach(element => {
            element.textContent = this.currentCurrency.symbol;
        });
        
        // Update currency symbols in stat numbers
        document.querySelectorAll('.stat-number').forEach(element => {
            const text = element.textContent;
            if (this.isCurrencyValue(text)) {
                const numericValue = this.extractNumericValue(text);
                if (numericValue !== null) {
                    element.textContent = this.formatCurrency(numericValue);
                }
            }
        });

        // Update currency symbols in price displays
        document.querySelectorAll('.price-display, .currency-value').forEach(element => {
            const text = element.textContent;
            if (this.isCurrencyValue(text)) {
                const numericValue = this.extractNumericValue(text);
                if (numericValue !== null) {
                    element.textContent = this.formatCurrency(numericValue);
                }
            }
        });
        
        // Update currency amounts with data-amount attribute
        document.querySelectorAll('.currency-amount[data-amount]').forEach(element => {
            const amount = parseFloat(element.getAttribute('data-amount')) || 0;
            const amountValue = element.querySelector('.amount-value');
            if (amountValue) {
                amountValue.textContent = amount.toLocaleString('en-US', {
                    minimumFractionDigits: 2,
                    maximumFractionDigits: 2
                });
            }
        });

        // Update any elements with data-currency-value attribute
        document.querySelectorAll('[data-currency-value]').forEach(element => {
            const value = element.getAttribute('data-currency-value');
            if (value) {
                element.textContent = this.formatCurrency(parseFloat(value));
            }
        });
    }

    isCurrencyValue(text) {
        // Check if text looks like a currency value
        return /^[^\d]*[\d,]+\.?\d*$/.test(text.trim());
    }

    extractNumericValue(text) {
        // Extract numeric value from currency string
        const match = text.replace(/[^\d.,]/g, '');
        if (match) {
            return parseFloat(match.replace(',', ''));
        }
        return null;
    }

    formatCurrency(value) {
        if (value === null || value === undefined || value === '') {
            return this.currentCurrency.symbol + '0.00';
        }
        let raw = String(value).replace(/,/g, '').replace(/[^\d.-]/g, '').trim();
        if (!raw || raw === '-' || raw === '.') {
            return this.currentCurrency.symbol + '0.00';
        }
        const neg = raw.startsWith('-');
        raw = raw.replace(/^-/, '');
        const parts = raw.split('.');
        let intPart = (parts[0] || '0').replace(/^0+(?=\d)/, '') || '0';
        let decPart = (parts[1] || '00').padEnd(2, '0').slice(0, 2);
        const asNum = Number((neg ? '-' : '') + intPart + '.' + decPart);
        if (Number.isFinite(asNum) && Math.abs(asNum) <= Number.MAX_SAFE_INTEGER) {
            return this.currentCurrency.symbol + asNum.toLocaleString('en-US', {
                minimumFractionDigits: 2,
                maximumFractionDigits: 2
            });
        }
        intPart = intPart.replace(/\B(?=(\d{3})+(?!\d))/g, ',');
        return this.currentCurrency.symbol + (neg ? '-' : '') + intPart + '.' + decPart;
    }

    addListener(callback) {
        this.listeners.push(callback);
    }

    removeListener(callback) {
        const index = this.listeners.indexOf(callback);
        if (index > -1) {
            this.listeners.splice(index, 1);
        }
    }

    notifyListeners(oldCurrency, newCurrency) {
        this.listeners.forEach(callback => {
            try {
                callback(oldCurrency, newCurrency);
            } catch (e) {
                console.error('Error in currency listener:', e);
            }
        });
    }

    // AJAX method to update currency on server
    async updateServerCurrency(currencyCode, currencySymbol) {
        try {
            const response = await fetch('/core/update-currency/', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this.getCSRFToken()
                },
                body: JSON.stringify({
                    currency_code: currencyCode
                })
            });

            const data = await response.json();
            if (data.success) {
                this.handleCurrencyUpdate({
                    currencyCode: data.currency_code,
                    currencySymbol: data.currency_symbol
                });
                return true;
            } else {
                console.error('Failed to update currency:', data.error);
                return false;
            }
        } catch (error) {
            console.error('Error updating currency:', error);
            return false;
        }
    }

    getCSRFToken() {
        const token = document.querySelector('[name=csrfmiddlewaretoken]');
        return token ? token.value : '';
    }
}

// Initialize global currency manager
window.currencyManager = new CurrencyManager();

// Utility function for easy access
window.updateCurrency = function(currencyCode, currencySymbol) {
    return window.currencyManager.updateServerCurrency(currencyCode, currencySymbol);
};

// Export for module systems
if (typeof module !== 'undefined' && module.exports) {
    module.exports = CurrencyManager;
} 