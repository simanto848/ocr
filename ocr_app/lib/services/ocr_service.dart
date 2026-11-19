import 'dart:io';

import 'package:path/path.dart' as p;
import 'package:tesseract_ocr/tesseract_ocr.dart';
import 'package:tesseract_ocr/ocr_engine_config.dart';

import '../models/extract_result.dart';
import 'languages.dart';

/// Fully offline extraction using bundled Tesseract language data.
class OcrService {
  static const imageExts = {'png', 'jpg', 'jpeg', 'webp', 'bmp', 'tif', 'tiff', 'gif'};
  static const textExts = {'txt', 'md', 'csv', 'log', 'json', 'xml', 'html', 'htm'};

  static bool supports(String path) {
    final ext = p.extension(path).replaceFirst('.', '').toLowerCase();
    return imageExts.contains(ext) || textExts.contains(ext);
  }

  static Future<ExtractResult> extract(
    String path, {
    required String languageChoice,
    void Function(String stage, int percent)? onProgress,
  }) async {
    final name = p.basename(path);
    final ext = p.extension(path).replaceFirst('.', '').toLowerCase();
    final lang = LanguageChoice.tessdataValue(languageChoice);

    if (textExts.contains(ext)) {
      onProgress?.call('reading file', 60);
      var text = await File(path).readAsString();
      if (ext == 'html' || ext == 'htm') {
        text = text.replaceAll(RegExp(r'<[^>]+>'), ' ').replaceAll(RegExp(r'\s+'), ' ');
      }
      onProgress?.call('done', 100);
      return ExtractResult.offline(
        filename: name,
        pages: [PageResult(page: 1, text: text.trim(), source: 'digital')],
        language: languageChoice,
      );
    }

    if (!imageExts.contains(ext)) {
      throw UnsupportedError(
        'Offline mode supports images and text files. Use Server mode for PDF, DOC and DOCX.',
      );
    }

    onProgress?.call('loading OCR engine', 5);
    final config = OCRConfig(
      language: lang,
      engine: OCREngine.tesseract,
      options: const {'preserve_interword_spaces': '1'},
    );
    onProgress?.call('recognising text', 35);
    final text = await TesseractOcr.extractText(path, config: config);
    onProgress?.call('done', 100);
    return ExtractResult.offline(
      filename: name,
      pages: [
        PageResult(
          page: 1,
          text: text.trim(),
          source: 'ocr',
        )
      ],
      language: languageChoice,
    );
  }
}
