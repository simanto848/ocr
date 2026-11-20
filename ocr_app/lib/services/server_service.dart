import 'dart:convert';

import 'package:http/http.dart' as http;
import 'package:path/path.dart' as p;

import '../models/extract_result.dart';
import 'languages.dart';

/// Client for the Python extraction server (full format + language support).
class ServerService {
  final String baseUrl;
  final String apiKey;

  ServerService(String url, {this.apiKey = ''})
      : baseUrl = url.trim().replaceFirst(RegExp(r'/+$'), '');

  Map<String, String> get _headers => apiKey.isEmpty ? {} : {'X-API-Key': apiKey};

  Uri _uri(String path) => Uri.parse('$baseUrl$path');

  Future<Map<String, dynamic>> status() async {
    final r = await http.get(_uri('/api/status'), headers: _headers)
        .timeout(const Duration(seconds: 8));
    if (r.statusCode != 200) throw Exception('Server returned ${r.statusCode}');
    return jsonDecode(r.body) as Map<String, dynamic>;
  }

  Future<ExtractResult> extract({
    required String path,
    required String languageChoice,
    void Function(String stage, int percent)? onProgress,
  }) async {
    final name = p.basename(path);
    onProgress?.call('uploading', 5);

    final request = http.MultipartRequest('POST', _uri('/api/upload'))
      ..headers.addAll(_headers)
      ..fields['lang'] = LanguageChoice.serverValue(languageChoice)
      ..files.add(await http.MultipartFile.fromPath('file', path));

    final streamed = await request.send().timeout(const Duration(seconds: 120));
    final response = await http.Response.fromStream(streamed);
    if (response.statusCode != 200) {
      String message = 'Upload failed (${response.statusCode})';
      try {
        message = (jsonDecode(response.body)['error'] as String?) ?? message;
      } catch (_) {}
      throw Exception(message);
    }
    final jobId = jsonDecode(response.body)['job_id'] as String;

    // Poll until the job finishes. Each response carries a progress object.
    while (true) {
      await Future.delayed(const Duration(milliseconds: 700));
      final r = await http.get(_uri('/api/job?id=${Uri.encodeComponent(jobId)}'));
      if (r.statusCode != 200) throw Exception('Could not read job status');
      final job = jsonDecode(r.body) as Map<String, dynamic>;
      final status = job['status'] as String?;
      final progress = job['progress'] as Map<String, dynamic>?;
      if (status == 'done') {
        onProgress?.call('done', 100);
        return ExtractResult.fromServer(job, filename: name);
      }
      if (status == 'error') {
        throw Exception(job['error'] ?? 'Server job failed');
      }
      onProgress?.call(
        (progress?['stage'] as String?) ?? 'processing',
        ((progress?['percent'] as num?) ?? 0).toInt(),
      );
    }
  }

  /// Fetch extracted text for download / sharing from the server.
  Future<String> downloadText(String jobId, String format) async {
    final r = await http.get(_uri('/api/download?job=${Uri.encodeComponent(jobId)}&format=$format'));
    if (r.statusCode != 200) throw Exception('Download failed (${r.statusCode})');
    return utf8.decode(r.bodyBytes);
  }
}
