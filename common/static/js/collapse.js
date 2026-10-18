$(document).ready(function () {
    $('.collapse').each(function () {
        const id = $(this).attr('id');
        if (!id) return;

        const isExpanded = localStorage.getItem('collapse_' + id);
        if (isExpanded === 'true') {
            $(this).addClass('show');
        } else {
            $(this).removeClass('show');
        }

        $(this).on('shown.bs.collapse', function () {
            localStorage.setItem('collapse_' + id, 'true');
        });

        $(this).on('hidden.bs.collapse', function () {
            localStorage.setItem('collapse_' + id, 'false');
        });
    });
});
