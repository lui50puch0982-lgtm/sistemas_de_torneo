/**
 * Plataforma Lucha Bolivia - Lógica JavaScript de Cliente
 */

document.addEventListener('DOMContentLoaded', function () {

    // 1. Cierre automático de mensajes Flash de Flask
    const flashAlerts = document.querySelectorAll('.alert-dismissible');
    flashAlerts.forEach(function (alert) {
        setTimeout(function () {
            const bsAlert = bootstrap.Alert.getOrCreateInstance(alert);
            if (bsAlert) {
                bsAlert.close();
            }
        }, 4000);
    });

    // 2. Buscador en tiempo real para tablas (Inscritos, Combates, Delegaciones)
    const tableSearchInput = document.getElementById('tableSearch');
    if (tableSearchInput) {
        tableSearchInput.addEventListener('keyup', function () {
            const filterValue = this.value.toLowerCase();
            const targetTable = document.querySelector(this.getAttribute('data-table-target') || 'table');
            const rows = targetTable.querySelectorAll('tbody tr');

            rows.forEach(function (row) {
                const text = row.textContent.toLowerCase();
                row.style.display = text.includes(filterValue) ? '' : 'none';
            });
        });
    }

    // 3. Confirmación previa para acciones críticas (Eliminar, Iniciar Torneo, Reset)
    const confirmButtons = document.querySelectorAll('[data-confirm]');
    confirmButtons.forEach(function (button) {
        button.addEventListener('click', function (e) {
            const message = this.getAttribute('data-confirm') || '¿Está seguro de realizar esta acción?';
            if (!confirm(message)) {
                e.preventDefault();
            }
        });
    });

    // 4. Control de validación de pesaje en tiempo real
    const inputPeso = document.querySelector('input[name="peso_oficial"]');
    if (inputPeso) {
        inputPeso.addEventListener('input', function () {
            if (parseFloat(this.value) < 0) {
                this.value = 0;
            }
        });
    }

    // 5. Auto-refresco en vivo para pantallas públicas/pantallas de tapiz
    const isPublicView = window.location.pathname.includes('/publico/');
    if (isPublicView) {
        // Refresca la vista cada 15 segundos para mantener las llaves/medallero actualizados
        setInterval(function () {
            window.location.reload();
        }, 15000);
    }
});