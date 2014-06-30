Mailpile.tag_list = function(complete) {
  $.ajax({
    url      : Mailpile.api.tag_list,
    type     : 'GET',
    dataType : 'json',
    success  : function(response) {
      if (response.status === 'success') {
        complete(response.result);
      }
    }
  });
};


/* Pile - Tag Add */
Mailpile.tag_add = function(tag_add, mids, complete) {
  $.ajax({
	  url			 : Mailpile.api.tag,
	  type		 : 'POST',
	  data     : {
      add: tag_add,
      mid: mids
    },
	  dataType : 'json',
    success  : function(response) {
      if (response.status == 'success') {
       complete(response.result);       
      } else {
        Mailpile.notification(response.status, response.message);
      }
    }
  });
};


Mailpile.tag_add_delete = function(tag_add, tag_del, mids, complete) {
  $.ajax({
	  url			 : Mailpile.api.tag,
	  type		 : 'POST',
	  data     : {
      add: tag_add,
      del: tag_del,
      mid: mids
    },
	  dataType : 'json',
    success  : function(response) {
      if (response.status == 'success') {
        complete(response.result);
      } else {
        Mailpile.notification(response.status, response.message);
      }
    }
  });
};


Mailpile.tag_update = function(tid, setting, value, complete) {

  // Prep Update Value
  var key = 'tags.' + tid + '.' + setting;
  var setting = {};
  setting[key] = value;

  $.ajax({
	  url			 : Mailpile.api.tag_update,
	  type		 : 'POST',
	  data     : setting,
	  dataType : 'json',
    success  : function(response) {
      if (response.status == 'success') {
        complete(response.result);
      } else {
        Mailpile.notification(response.status, response.message);
      }
    }
  });
};


Mailpile.render_modal_tags = function() {
  if (Mailpile.messages_cache.length) {

    // Open Modal with selection options
    Mailpile.tag_list(function(result) {
  
      var tags_html = '';
      var archive_html = '';
  
      $.each(result.tags, function(key, value) {
        if (value.display === 'tag') {
          tags_html += '<li class="checkbox-item-picker" data-tid="' + value.tid + '" data-slug="' + value.slug + '"><input type="checkbox"> ' + value.name + '</li>';
        }
        else if (value.display === 'archive') {
          archive_html += '<li class="checkbox-item-picker" data-tid="' + value.tid + '" data-slug="' + value.slug + '"><input type="checkbox"> ' + value.name + '</li>';
        }
      });
  
      var modal_html = $("#modal-tag-picker").html();
      $('#modal-full').html(_.template(modal_html, { tags: tags_html, archive: archive_html }));
      $('#modal-full').modal({ backdrop: true, keyboard: true, show: true, remote: false });
    });
 
  } else {
    // FIXME: Needs more internationalization support
    alert('No Messages Selected');
  }
};


$(document).on('click', '#button-tag-change-icon', function() {

  var icons_html = '';
  $.each(Mailpile.theme.icons, function(key, icon) {
    icons_html += '<li class="modal-tag-icon-option ' + icon + '" data-icon="' + icon + '"></li>';
  });

  var modal_html = $("#modal-tag-icon-picker").html();
  $('#modal-full').html(_.template(modal_html, { icons: icons_html }));
  $('#modal-full').modal({ backdrop: true, keyboard: true, show: true, remote: false });
});


$(document).on('click', '.modal-tag-icon-option', function() {

  var tid  = $('#data-tag-tid').val();
  var old  = $('#data-tag-icon').val();
  var icon = $(this).data('icon');

  Mailpile.tag_update(tid, 'icon', icon, function() {

    // Update Sidebar
    $('#sidebar-tag-' + tid).find('span.sidebar-icon').removeClass(old).addClass(icon);

    // Update Tag Editor
    $('#data-tag-icon').val(icon);
    $('#tag-editor-icon').removeClass().addClass(icon);
    $('#modal-full').modal('hide');
  });
});


$(document).on('click', '#button-tag-change-label-color', function(e) {
  
  var sorted_colors =  _.keys(Mailpile.theme.colors).sort();
  var colors_html = '';
  $.each(sorted_colors, function(key, name) {
    var hex = Mailpile.theme.colors[name];
    colors_html += '<li><a href="#" class="modal-tag-color-option" style="background-color: ' + hex + '" data-name="' + name + '" data-hex="' + hex + '"></a></li>';
  });

  var modal_html = $("#modal-tag-color-picker").html();
  $('#modal-full').html(_.template(modal_html, { colors: colors_html }));
  $('#modal-full').modal({ backdrop: true, keyboard: true, show: true, remote: false });
});


$(document).on('click', '.modal-tag-color-option', function(e) {

  var tid   = $('#data-tag-tid').val();
  var old   = $('#data-tag-label-color').val();
  var name = $(this).data('name');
  var hex = $(this).data('hex');

  Mailpile.tag_update(tid, 'label_color', name, function() {

    // Update Sidebar
    $('#sidebar-tag-' + tid).find('span.sidebar-icon').css('color', hex);

    // Update Tag Editor
    $('#data-tag-label-color').val(name);
    $('#tag-editor-icon').css('color', hex);
    $('#modal-full').modal('hide');
  });
});


/* API - Tag Add */
$(document).on('submit', '#form-tag-add', function(e) {

  e.preventDefault();
  var tag_data = $('#form-tag-add').serialize();

  $.ajax({
    url: Mailpile.api.tag_add,
    type: 'POST',
    data: tag_data,
    dataType : 'json',
    success: function(response) {

      Mailpile.notification(response.status, response.message);

      if (response.status === 'success') {
      
        // Reset form fields
        $('#data-tag-add-tag').val('');
        $('#data-tag-add-slug').val('');
        $('#data-tag-add-display option[value="tag"]').prop("selected", true);
        $('#data-tag-add-parrent option[value=""]').prop("selected", true);
        $('#data-tag-add-template option[value="default"]').prop("selected", true);
        $('#data-tag-add-search-terms').val('');
        
        // Reset Slugify
        $('#data-tag-add-slug').slugify('#data-tag-add-tag');
      }
    }
  });
});


/* Tag - Delete Tag */
$(document).on('click', '#button-tag-delete', function(e) {
  if (confirm('Sure you want to delete this tag?') === true) { 
    $.ajax({
      url: '/api/0/tag/delete/',
      type: 'POST',
      data: {tag: $('#data-tag-add-slug').val() },
      dataType : 'json',
      success: function(response) {
        Mailpile.notification(response.status, response.message, 'redirect', Mailpile.urls.tags);
      }
    });
  }
});


/* Tag - Toggle Archive */
$(document).on('click', '#button-tag-toggle-archive', function(e) {
  var new_message = $(this).data('message');
  var old_message = $(this).html();
  $(this).data('message', old_message);
  $(this).html(new_message);
  if ($('#tags-archived-list').hasClass('hide')) {
    $('#tags-archived-list').removeClass('hide');
  } else {
    $('#tags-archived-list').addClass('hide');    
  }
});


/* Tag - Update */
$(document).on('blur', '#data-tag-add-tag', function(e) {

  alert('Saving: ' + $(this).val())  

});


/* Tag - Update (multiple attribute events) */
$(document).on('change', '#data-tag-display', function(e) {
  Mailpile.tag_update($('#data-tag-tid').val(), 'display', $(this).val(), function() {
    // FIXME: show (or move) change update in sidebar
  });  
});


$(document).on('change', '#data-tag-parent', function(e) {
  Mailpile.tag_update($('#data-tag-tid').val(), 'parent', $(this).val(), function() {
    // FIXME: show (or move) change update in sidebar
  });  
});