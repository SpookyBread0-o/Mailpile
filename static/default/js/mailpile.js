
Number.prototype.pad = function(size){
	// Unfortunate padding function....
	if(typeof(size) !== "number"){size = 2;}
	var s = String(this);
	while (s.length < size) s = "0" + s;
	return s;
}


function MailPile() {
	this.msgcache = [];
	this.searchcache = [];
}

MailPile.prototype.add = function() {}
MailPile.prototype.attach = function() {}
MailPile.prototype.compose = function() {}
MailPile.prototype.delete = function() {}
MailPile.prototype.extract = function() {}
MailPile.prototype.filter = function() {}
MailPile.prototype.help = function() {}
MailPile.prototype.load = function() {}
MailPile.prototype.mail = function() {}
MailPile.prototype.forward = function() {}
MailPile.prototype.next = function() {}
MailPile.prototype.order = function() {}
MailPile.prototype.optimize = function() {}
MailPile.prototype.previous = function() {}
MailPile.prototype.print = function() {}
MailPile.prototype.reply = function() {}
MailPile.prototype.rescan = function() {}

MailPile.prototype.gpgrecv = function(keyid) {

}

MailPile.prototype.gpglistkeys = function() {
	mailpile.json_get("gpg list", {}, function(data) {
		$("#content").append('<div class="dialog" id="gpgkeylist"></div>');
		for (k in data.results) {
			key = data.results[k]
			$("#gpgkeylist").append("<li>Key: " + key.uids[0].replace("<", "&lt;").replace(">", "&gt;") + ": " + key.pub.keyid + "</li>");
		}
	});
}

MailPile.prototype.search = function(q) {
	var that = this;
	$("#qbox").val(q);
	this.json_get("search", {"q": q}, function(data) {
		if ($("#results").length == 0) {
			$("#content").prepend('<table id="results" class="results"><tbody></tbody></table>');
		}
		$("#results tbody").empty();
		for (var i = 0; i < data.results.length; i++) {
			msg_info = data.results[i];
			msg_tags = data.results[i].tags;
			d = new Date(msg_info.date*1000)
			zpymd = d.getFullYear() + "-" + (d.getMonth()+1).pad(2) + "-" + d.getDate().pad(2);
			ymd = d.getFullYear() + "-" + (d.getMonth()+1) + "-" + d.getDate();
			taghrefs = msg_tags.map(function(e){ return '<a onclick="mailpile.search(\'\\' + e + '\')">' + e + '</a>'}).join(" ");
			tr = $('<tr class="result"></tr>');
			tr.addClass((i%2==0)?"even":"odd");
			tr.append('<td class="checkbox"><input type="checkbox" name="msg_' + msg_info.id + '"/></td>');
			tr.append('<td class="from"><a href="' + msg_info.url + '">' + msg_info.from + '</a></td>');
			tr.append('<td class="subject"><a href="' + msg_info.url + '">' + msg_info.subject + '</a></td>');
			tr.append('<td class="tags">' + taghrefs + '</td>');
			tr.append('<td class="date"><a onclick="mailpile.search(\'date:' + ymd + '\');">' + zpymd + '</a></td>');
			$("#results tbody").append(tr);
		}
		that.loglines(data.chatter);
	});
}

MailPile.prototype.set = function(key, value) {
	var that = this;
	this.json_get("set", {"args": key + "=" + value}, function(data) {
		if (data.status == "ok") {
			that.notice("Success: " + data.loglines[0]);
		} else if (data.status == "error") {
			this.error(data.loglines[0]);
		}
	});
}

MailPile.prototype.tag = function(msgids, tags) {}
MailPile.prototype.addtag = function(tagname) {}
MailPile.prototype.unset = function() {}
MailPile.prototype.update = function() {}

MailPile.prototype.view = function(idx, msgid) {
	var that = this;
	this.json_get("view", {"idx": idx, "msgid": msgid}, function(data) {
		if ($("#results").length == 0) {
			$("#content").prepend('<table id="results" class="results"><tbody></tbody></table>');
		}
		$("#results").empty();
		$that.loglines(data.chatter);
	})
}

MailPile.prototype.json_get = function(cmd, params, callback) {
	var url;
	if (cmd == "view") {
		url = "/=" + params["idx"] + "/" + params["msgid"] + ".json";
	} else {
		url = "/_/" + cmd + ".json";
	}
	$.getJSON(url, params, callback);
}

MailPile.prototype.loglines = function(text) {
	$("#loglines").empty();
	for (var i = 0; i < text.length; i++) {
		$("#loglines").append(text[i] + "\n");
	}
}

MailPile.prototype.notice = function(msg) {
	console.log("NOTICE: " + msg);
}

MailPile.prototype.error = function(msg) {
	console.log("ERROR: " + msg);
}

MailPile.prototype.warning = function(msg) {
	console.log("WARNING: " + msg);
}


var mailpile = new MailPile();

// Non-exposed functions: www, setup
$(document).ready(function() {

	/* Hide Various Things */
	$('#search-params, #bulk-actions').hide();



	/* Search Box */
	$('#qbox').jkey('enter, return', function(key) {	
    	console.log('Search query submitted');
		$('#search-params').slideDown('fast');
	});



	/* Bulk Actions */
	$('.bulk-action').on('click', function(e) {

		e.preventDefault();
		
		var checkboxes = $('#pile-results input[type=checkbox]');
		var action = $(this).attr('href');
		var count = 0;
		
		$.each(checkboxes, function() {

			if ($(this).val() === 'selected') {
				console.log('This is here ' + $(this).attr('name'));
				
				count++;
			}
			
		});
		
		
		alert(count + ' items selected to "' + action.replace('#', '') + '"');

	});


	/* Result Actions */
	var pileActionSelect = function(item) {

		// Increment Selected
		$('#bulk-actions-selected-count').html(parseInt($('#bulk-actions-selected-count').html()) + 1);

		// Show Actions
		$('#bulk-actions').slideDown('fast');

		// Style & Select Checkbox
		item.removeClass('result').addClass('result-on')
		.data('state', 'selected')
		.find('td.checkbox input[type=checkbox]')
		.val('selected')
		.prop('checked', true);	
	}

	var pileActionUnselect = function(item) {

		// Decrement Selected
		var selected_count = parseInt($('#bulk-actions-selected-count').html()) - 1;

		$('#bulk-actions-selected-count').html(selected_count);

		// Hide Actions
		if (selected_count < 1) {
			$('#bulk-actions').slideUp('fast');
		}

		// Style & Unselect Checkbox
		item.removeClass('result-on').addClass('result')
		.data('state', 'normal')
		.find('td.checkbox input[type=checkbox]')
		.val('normal')
		.prop('checked', false);
	}

	$('#pile-results').on('click', 'tr', function() {		
		if ($(this).data('state') === 'selected') {
			pileActionUnselect($(this));
		}
		else {
			pileActionSelect($(this));
		}
	});



	/* OLD UNUSED STUFF */
	function focus(eid) {var e = document.getElementById(eid);e.focus();
	if (e.setSelectionRange) {var l = 2*e.value.length;e.setSelectionRange(l,l)}
	else {e.value = e.value;}}

});	
