(function() {
    // 针对 HTTP 环境下 navigator.clipboard 不存在的兼容性补丁
    if (!navigator.clipboard) {
        console.log("Navigator.clipboard is missing, applying polyfill...");
        navigator.clipboard = {
            writeText: function(text) {
                return new Promise(function(resolve, reject) {
                    var textArea = document.createElement("textarea");
                    textArea.value = text;
                    textArea.style.position = "fixed";
                    textArea.style.left = "-9999px";
                    textArea.style.top = "0";
                    document.body.appendChild(textArea);
                    textArea.focus();
                    textArea.select();
                    try {
                        var successful = document.execCommand('copy');
                        document.body.removeChild(textArea);
                        if (successful) {
                            resolve();
                        } else {
                            reject(new Error('Unable to copy text'));
                        }
                    } catch (err) {
                        document.body.removeChild(textArea);
                        reject(err);
                    }
                });
            }
        };
    }
})();
