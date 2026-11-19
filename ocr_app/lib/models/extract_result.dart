import 'dart:convert';

class PageResult {
  final int page;
  final String text;
  final String source; // 'ocr' | 'digital'
  final String? note;

  const PageResult({
    required this.page,
    required this.text,
    required this.source,
    this.note,
  });

  factory PageResult.fromJson(Map<String, dynamic> j) => PageResult(
        page: (j['page'] as num?)?.toInt() ?? 1,
        text: (j['text'] as String?) ?? '',
        source: (j['source'] as String?) ?? 'ocr',
        note: j['note'] as String?,
      );

  Map<String, dynamic> toJson() => {
        'page': page,
        'text': text,
        'source': source,
        if (note != null) 'note': note,
      };
}

class ExtractResult {
  final String filename;
  final List<PageResult> pages;
  final String engine;
  final String language;
  final bool offline;

  const ExtractResult({
    required this.filename,
    required this.pages,
    required this.engine,
    required this.language,
    required this.offline,
  });

  factory ExtractResult.fromServer(Map<String, dynamic> job, {required String filename}) {
    final pages = ((job['pages'] as List?) ?? [])
        .map((p) => PageResult.fromJson(p as Map<String, dynamic>))
        .toList();
    return ExtractResult(
      filename: filename,
      pages: pages,
      engine: (job['engine'] as String?) ?? 'server',
      language: (job['language'] as String?) ?? 'auto',
      offline: false,
    );
  }

  factory ExtractResult.offline({
    required String filename,
    required List<PageResult> pages,
    required String language,
  }) =>
      ExtractResult(
        filename: filename,
        pages: pages,
        engine: 'Tesseract (on-device)',
        language: language,
        offline: true,
      );

  String get fullText => pages.map((p) => p.text).join('\n\n');

  String toJsonString() => jsonEncode({
        'file': filename,
        'engine': engine,
        'language': language,
        'mode': offline ? 'offline' : 'server',
        'pages': pages.map((p) => p.toJson()).toList(),
      }, toEncodable: (_) => null);
}
