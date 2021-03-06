(function($, window){

	var detail = function(appName, envs) {
		var allGraphs = function(appName, envs) {
			var kinds = ["mem_max", "cpu_max", "connections", "units", "response_time", "requests_min"];
			$(".metrics-container").css("display", "block");
			$.each(kinds, function(i, kind) {
				var opts = {
					appName: appName,
					serie: "1m",
					from: "1h/h",
					hover: false,
					kind: kind,
					envs: envs
				}
				$.Graph(opts);
			});
		};

		allGraphs(appName, envs);
		$.confirmation(".btn-remove", ".remove-confirmation", appName);
		$.confirmation(".btn-unlock", ".unlock-confirmation", appName);
	};

	$.detail = detail;

})(jQuery, window);
