import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:image_picker/image_picker.dart';
import 'package:path/path.dart' as p;
import 'package:share_plus/share_plus.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../models/extract_result.dart';
import '../services/languages.dart';
import '../services/ocr_service.dart';
import '../services/server_service.dart';

enum ExtractMode { offline, server }

class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key});

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  final _urlController = TextEditingController(text: 'http://10.0.2.2:8000');
  SharedPreferences? _prefs;

  ExtractMode _mode = ExtractMode.server;
  String _language = 'auto';
  String? _filePath;
  String? _fileName;

  ExtractResult? _result;
  String? _error;
  String _stage = '';
  int _percent = 0;
  bool _busy = false;
  bool _showJson = false;
  String? _serverInfo;

  @override
  void initState() {
    super.initState();
    _loadPrefs();
  }

  Future<void> _loadPrefs() async {
    final prefs = await SharedPreferences.getInstance();
    _prefs = prefs;
    setState(() {
      _mode = (prefs.getString('mode') == 'offline') ? ExtractMode.offline : ExtractMode.server;
      _language = prefs.getString('language') ?? 'auto';
      _urlController.text = prefs.getString('serverUrl') ?? 'http://10.0.2.2:8000';
    });
  }

  Future<void> _savePrefs() async {
    final prefs = _prefs;
    if (prefs == null) return;
    await prefs.setString('mode', _mode.name);
    await prefs.setString('language', _language);
    await prefs.setString('serverUrl', _urlController.text.trim());
  }

  void _notify(String message) {
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(message)));
  }

  Future<void> _pickFile() async {
    final files = await FilePicker.pickFiles(type: FileType.any);
    if (files.isEmpty || files.first.path == null) return;
    _setFile(files.first.path!, files.first.name);
  }

  Future<void> _takePhoto() async {
    final x = await ImagePicker().pickImage(source: ImageSource.camera, imageQuality: 92);
    if (x == null) return;
    _setFile(x.path, p.basename(x.path));
  }

  void _setFile(String path, String name) {
    setState(() {
      _filePath = path;
      _fileName = name;
      _result = null;
      _error = null;
      _percent = 0;
      _stage = '';
    });
  }

  void _progress(String stage, int percent) {
    if (!mounted) return;
    setState(() {
      _stage = stage;
      _percent = percent.clamp(0, 100);
    });
  }

  Future<void> _extract() async {
    final path = _filePath;
    if (path == null) {
      setState(() => _error = 'Please choose a file first.');
      return;
    }
    setState(() {
      _busy = true;
      _error = null;
      _result = null;
      _percent = 0;
      _stage = 'starting';
    });
    try {
      final ExtractResult result;
      if (_mode == ExtractMode.offline) {
        result = await OcrService.extract(path, languageChoice: _language, onProgress: _progress);
      } else {
        final service = ServerService(_urlController.text);
        result = await service.extract(path: path, languageChoice: _language, onProgress: _progress);
      }
      if (!mounted) return;
      setState(() => _result = result);
    } catch (e) {
      if (!mounted) return;
      setState(() => _error = e.toString().replaceFirst('Exception: ', ''));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _testServer() async {
    setState(() {
      _error = null;
      _serverInfo = 'connecting…';
    });
    try {
      final info = await ServerService(_urlController.text).status();
      if (!mounted) return;
      setState(() => _serverInfo = '${info['engine']} · ${(info['languages'] as List?)?.join(', ')}');
      await _savePrefs();
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _serverInfo = null;
        _error = 'Cannot reach server: ${e.toString().replaceFirst('Exception: ', '')}';
      });
    }
  }

  @override
  void dispose() {
    _urlController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    return Scaffold(
      appBar: AppBar(
        title: const Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          mainAxisSize: MainAxisSize.min,
          children: [
            Text('DocExtract', style: TextStyle(fontSize: 18)),
            Text('PDF · DOC · Images → English / বাংলা / हिन्दी',
                style: TextStyle(fontSize: 11, fontWeight: FontWeight.normal)),
          ],
        ),
        actions: [
          IconButton(
            tooltip: 'Help',
            icon: const Icon(Icons.help_outline),
            onPressed: _showHelp,
          ),
        ],
      ),
      body: SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(16),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              _section('Mode', child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  SegmentedButton<ExtractMode>(
                    segments: const [
                      ButtonSegment(value: ExtractMode.offline, label: Text('Offline'), icon: Icon(Icons.phone_android)),
                      ButtonSegment(value: ExtractMode.server, label: Text('Server'), icon: Icon(Icons.cloud)),
                    ],
                    selected: {_mode},
                    onSelectionChanged: (s) {
                      setState(() => _mode = s.first);
                      _savePrefs();
                    },
                  ),
                  const SizedBox(height: 8),
                  Text(
                    _mode == ExtractMode.offline
                        ? 'On-device OCR — works with no internet. Images, photos and text files. For PDF/DOC use Server mode.'
                        : 'Send any file (PDF, DOC, DOCX, images…) to the Python server for full multilingual extraction.',
                    style: TextStyle(fontSize: 12.5, color: cs.onSurface.withValues(alpha:.65)),
                  ),
                ],
              )),
              const SizedBox(height: 12),
              _section('OCR language', child: DropdownButtonFormField<String>(
                initialValue: _language,
                decoration: const InputDecoration(
                  prefixIcon: Icon(Icons.translate),
                  border: OutlineInputBorder(),
                  isDense: true,
                ),
                items: LanguageChoice.all
                    .map((l) => DropdownMenuItem(value: l.value, child: Text(l.label)))
                    .toList(),
                onChanged: (v) {
                  if (v == null) return;
                  setState(() => _language = v);
                  _savePrefs();
                },
              )),
              if (_mode == ExtractMode.server) ...[
                const SizedBox(height: 12),
                _section('Server address', child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    TextField(
                      controller: _urlController,
                      keyboardType: TextInputType.url,
                      decoration: const InputDecoration(
                        hintText: 'http://192.168.1.10:8000',
                        prefixIcon: Icon(Icons.dns),
                        border: OutlineInputBorder(),
                        isDense: true,
                      ),
                    ),
                    const SizedBox(height: 8),
                    Row(
                      children: [
                        OutlinedButton.icon(
                          onPressed: _testServer,
                          icon: const Icon(Icons.wifi_find, size: 16),
                          label: const Text('Test connection'),
                        ),
                        const SizedBox(width: 10),
                        Expanded(
                          child: Text(
                            _serverInfo ?? 'Emulator: http://10.0.2.2:8000 · phone: your computer’s LAN IP',
                            style: TextStyle(fontSize: 11.5, color: cs.onSurface.withValues(alpha:.6)),
                          ),
                        ),
                      ],
                    ),
                  ],
                )),
              ],
              const SizedBox(height: 12),
              _section('Document', child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Row(
                    children: [
                      Expanded(
                        child: OutlinedButton.icon(
                          onPressed: _pickFile,
                          icon: const Icon(Icons.folder_open),
                          label: const Text('Choose file'),
                          style: OutlinedButton.styleFrom(minimumSize: const Size(0, 48)),
                        ),
                      ),
                      const SizedBox(width: 10),
                      Expanded(
                        child: OutlinedButton.icon(
                          onPressed: _takePhoto,
                          icon: const Icon(Icons.photo_camera),
                          label: const Text('Take photo'),
                          style: OutlinedButton.styleFrom(minimumSize: const Size(0, 48)),
                        ),
                      ),
                    ],
                  ),
                  if (_fileName != null) ...[
                    const SizedBox(height: 10),
                    Container(
                      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
                      decoration: BoxDecoration(
                        color: cs.primaryContainer,
                        borderRadius: BorderRadius.circular(10),
                      ),
                      child: Row(
                        children: [
                          Icon(Icons.insert_drive_file, size: 18, color: cs.onPrimaryContainer),
                          const SizedBox(width: 8),
                          Expanded(child: Text(_fileName!, style: TextStyle(color: cs.onPrimaryContainer))),
                          IconButton(
                            icon: const Icon(Icons.close, size: 18),
                            color: cs.onPrimaryContainer,
                            onPressed: () => setState(() {
                              _filePath = null;
                              _fileName = null;
                              _result = null;
                            }),
                          ),
                        ],
                      ),
                    ),
                  ],
                ],
              )),
              const SizedBox(height: 14),
              FilledButton.icon(
                onPressed: _busy ? null : _extract,
                icon: const Icon(Icons.text_fields),
                label: Text(_busy ? 'Extracting…' : 'Extract text'),
                style: FilledButton.styleFrom(minimumSize: const Size.fromHeight(50)),
              ),
              if (_busy) ...[
                const SizedBox(height: 12),
                LinearProgressIndicator(value: _percent / 100.0),
                const SizedBox(height: 6),
                Text('$_stage · $_percent%', textAlign: TextAlign.center,
                    style: TextStyle(fontSize: 12, color: cs.onSurface.withValues(alpha:.7))),
              ],
              if (_error != null) ...[
                const SizedBox(height: 12),
                Container(
                  padding: const EdgeInsets.all(12),
                  decoration: BoxDecoration(
                    color: cs.errorContainer,
                    borderRadius: BorderRadius.circular(10),
                  ),
                  child: Row(children: [
                    Icon(Icons.error_outline, color: cs.onErrorContainer),
                    const SizedBox(width: 8),
                    Expanded(child: Text(_error!, style: TextStyle(color: cs.onErrorContainer))),
                  ]),
                ),
              ],
              if (_result != null) ...[
                const SizedBox(height: 16),
                _buildResult(cs),
              ],
            ],
          ),
        ),
      ),
    );
  }

  Widget _section(String title, {required Widget child}) {
    final cs = Theme.of(context).colorScheme;
    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: cs.surfaceContainerLow,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: cs.outline.withValues(alpha:.15)),
      ),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text(title, style: TextStyle(fontSize: 12, fontWeight: FontWeight.w700, color: cs.primary)),
        const SizedBox(height: 10),
        child,
      ]),
    );
  }

  Widget _buildResult(ColorScheme cs) {
    final r = _result!;
    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: cs.surfaceContainerLow,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: cs.outline.withValues(alpha:.15)),
      ),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Expanded(child: Text(r.filename, style: const TextStyle(fontWeight: FontWeight.w700))),
          Chip(
            label: Text(r.offline ? 'Offline' : 'Server', style: const TextStyle(fontSize: 11)),
            visualDensity: VisualDensity.compact,
          ),
        ]),
        const SizedBox(height: 4),
        Text('${r.engine}  ·  ${r.language}  ·  ${r.pages.length} page(s)',
            style: TextStyle(fontSize: 11.5, color: cs.onSurface.withValues(alpha:.6))),
        const SizedBox(height: 10),
        Row(children: [
          ChoiceChip(
            label: const Text('Text'),
            selected: !_showJson,
            onSelected: (_) => setState(() => _showJson = false),
          ),
          const SizedBox(width: 6),
          ChoiceChip(
            label: const Text('JSON'),
            selected: _showJson,
            onSelected: (_) => setState(() => _showJson = true),
          ),
          const Spacer(),
          IconButton(
            tooltip: 'Copy',
            icon: const Icon(Icons.copy),
            onPressed: () {
              Clipboard.setData(ClipboardData(
                  text: _showJson ? r.toJsonString() : r.fullText));
              _notify('Copied to clipboard');
            },
          ),
          IconButton(
            tooltip: 'Share',
            icon: const Icon(Icons.share),
            onPressed: () => SharePlus.instance.share(ShareParams(
              text: _showJson ? r.toJsonString() : r.fullText,
              subject: 'Extracted text: ${r.filename}',
            )),
          ),
        ]),
        const Divider(),
        if (r.pages.length > 1)
          SizedBox(
            height: 34,
            child: ListView.separated(
              scrollDirection: Axis.horizontal,
              itemCount: r.pages.length,
              separatorBuilder: (_, _) => const SizedBox(width: 6),
              itemBuilder: (context, i) => ActionChip(
                label: Text('Page ${r.pages[i].page}'),
                onPressed: () => _notify('Page ${r.pages[i].page}: ${r.pages[i].source}'),
              ),
            ),
          ),
        const SizedBox(height: 8),
        SelectableText(
          _showJson ? r.toJsonString() : (r.fullText.isEmpty ? '(no text detected)' : r.fullText),
          style: const TextStyle(fontSize: 14, height: 1.5),
        ),
      ]),
    );
  }

  void _showHelp() {
    showDialog(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('How to use'),
        content: const Text(
          '1. Choose Server mode and point it at the Python web app running on your computer '
          '(run web/run.sh, then use http://YOUR-PC-IP:8000). Server mode handles PDF, DOC, '
          'DOCX, RTF, ODT, TXT, HTML and images, in English, বাংলা and हिन्दी.\n\n'
          '2. Choose Offline mode to OCR photos/images directly on the phone with no server. '
          'Text files are read as-is.\n\n'
          '3. Pick the OCR language, choose a file, then tap “Extract text”. Copy or share the result.',
        ),
        actions: [TextButton(onPressed: () => Navigator.pop(context), child: const Text('OK'))],
      ),
    );
  }
}
