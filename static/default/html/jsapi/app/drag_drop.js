/* Search - Options for sidebar */
Mailpile.sidebar_tags_droppable_opts = {
  accept: 'td.draggable',
  activeClass: 'sidebar-tags-draggable-hover',
  hoverClass: 'sidebar-tags-draggable-active',
  tolerance: 'pointer',
  over: function(event, ui) {
    var tid = $(this).find('a').data('tid');
    setTimeout(function() {
      //Mailpile.ui_sidebar_toggle_subtags(tid, 'open');
    }, 500);
  },
  out: function(event, ui) {
    var tid = $(this).find('a').data('tid');
    setTimeout(function() {
      //Mailpile.ui_sidebar_toggle_subtags(tid, 'close');
    }, 1000);
  },
  drop: function(event, ui) {

    var tid = $(this).find('a').data('tid');

    // Add MID to Cache
    Mailpile.bulk_cache_add('messages_cache', ui.draggable.parent().data('mid'));

    // Add / Delete
    Mailpile.tag_add_delete(tid, Mailpile.instance.search_tag_ids, Mailpile.messages_cache, function() {

      // Update Pile View
      $.each(Mailpile.messages_cache, function(key, mid) {
        $('#pile-message-' + mid).fadeOut('fast');
      });

      // Empty Bulk Cache
      Mailpile.messages_cache = [];

      // Update Bulk UI
      Mailpile.bulk_actions_update_ui();

      // Hide Collapsible
      Mailpile.ui_sidebar_toggle_subtags(tid, 'close');
    });
  }
};


/* Search - Make search items draggable to sidebar */
$('li.sidebar-tags-draggable').droppable(Mailpile.sidebar_tags_droppable_opts);