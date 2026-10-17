import UIKit
import UniformTypeIdentifiers

/// The share sheet's way into Initiative. It writes what was shared where the app can read it —
/// the App Group both of them belong to, under the key the share-target plugin reads — and opens
/// the app, which shows the share page. If the app cannot be opened from here, the plugin reads
/// the share the next time the app comes to the foreground.
final class ShareViewController: UIViewController {
    private let appGroupId = "group.studio.beyonders.initiative"
    private let shareKey = "share-target-data"
    private let appURL = URL(string: "initiative://share")!
    /// Pictures older than this are left over from a share the app never read.
    private let staleAfter: TimeInterval = 24 * 60 * 60

    private var handedOff = false

    override func viewDidAppear(_ animated: Bool) {
        super.viewDidAppear(animated)
        guard !handedOff else { return }
        handedOff = true
        Task { await handOff() }
    }

    private func handOff() async {
        let items = extensionContext?.inputItems as? [NSExtensionItem] ?? []
        var title = ""
        var texts: [String] = []
        var files: [[String: String]] = []

        if let directory = sharedFilesDirectory() {
            removeStaleFiles(in: directory)
        }

        for item in items {
            if title.isEmpty, let itemTitle = item.attributedTitle?.string {
                title = itemTitle
            }
            if let content = item.attributedContentText?.string, !content.isEmpty {
                texts.append(content)
            }
            for provider in item.attachments ?? [] {
                if provider.hasItemConformingToTypeIdentifier(UTType.image.identifier) {
                    if let file = await savedFile(from: provider, as: .image) {
                        files.append(file)
                    }
                } else if provider.hasItemConformingToTypeIdentifier(UTType.url.identifier) {
                    // A file shared from Files arrives as a file URL, which is a URL too.
                    guard let url = try? await provider.loadItem(forTypeIdentifier: UTType.url.identifier) as? URL else {
                        continue
                    }
                    if !url.isFileURL {
                        texts.append(url.absoluteString)
                    } else if let file = savedFile(at: url) {
                        files.append(file)
                    }
                } else if provider.hasItemConformingToTypeIdentifier(UTType.plainText.identifier) {
                    if let text = try? await provider.loadItem(forTypeIdentifier: UTType.plainText.identifier) as? String {
                        texts.append(text)
                    }
                } else if let type = provider.registeredContentTypes.first(where: { $0.conforms(to: .data) }) {
                    if let file = await savedFile(from: provider, as: type) {
                        files.append(file)
                    }
                }
            }
        }

        let defaults = UserDefaults(suiteName: appGroupId)
        defaults?.set(["title": title, "texts": texts, "files": files], forKey: shareKey)
        defaults?.synchronize()

        await MainActor.run {
            openApp()
            extensionContext?.completeRequest(returningItems: nil)
        }
    }

    /// A shared file, copied into the App Group so the app can read it after this extension ends.
    private func savedFile(from provider: NSItemProvider, as requested: UTType) async -> [String: String]? {
        guard let item = try? await provider.loadItem(forTypeIdentifier: requested.identifier) else {
            return nil
        }
        if let url = item as? URL {
            return savedFile(at: url)
        }

        let name = provider.suggestedName ?? "file"
        if let image = item as? UIImage, let data = image.jpegData(compressionQuality: 0.9) {
            return saved(data, name: name, type: .jpeg)
        }
        if let data = item as? Data {
            let type = provider.registeredContentTypes.first { $0.conforms(to: requested) } ?? requested
            return saved(data, name: name, type: type)
        }
        return nil
    }

    private func savedFile(at url: URL) -> [String: String]? {
        guard let data = try? Data(contentsOf: url) else { return nil }
        return saved(data, name: url.lastPathComponent, type: UTType(filenameExtension: url.pathExtension))
    }

    private func saved(_ data: Data, name: String, type: UTType?) -> [String: String]? {
        guard let directory = sharedFilesDirectory() else { return nil }
        let fileExtension = type?.preferredFilenameExtension ?? (name as NSString).pathExtension
        let destination = directory.appendingPathComponent(UUID().uuidString)
            .appendingPathExtension(fileExtension)
        do {
            try data.write(to: destination)
        } catch {
            return nil
        }
        return [
            "uri": destination.path,
            "name": name,
            "mimeType": type?.preferredMIMEType ?? "application/octet-stream",
        ]
    }

    private func sharedFilesDirectory() -> URL? {
        guard let container = FileManager.default.containerURL(
            forSecurityApplicationGroupIdentifier: appGroupId
        ) else {
            return nil
        }
        let directory = container.appendingPathComponent("SharedFiles", isDirectory: true)
        try? FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        return directory
    }

    private func removeStaleFiles(in directory: URL) {
        let manager = FileManager.default
        guard let entries = try? manager.contentsOfDirectory(
            at: directory,
            includingPropertiesForKeys: [.contentModificationDateKey]
        ) else {
            return
        }
        let cutoff = Date().addingTimeInterval(-staleAfter)
        for entry in entries {
            let modified = (try? entry.resourceValues(forKeys: [.contentModificationDateKey]))?
                .contentModificationDate
            if let modified, modified < cutoff {
                try? manager.removeItem(at: entry)
            }
        }
    }

    /// An extension has no `UIApplication.shared`; the application is reached up the responder chain.
    private func openApp() {
        var responder: UIResponder? = self
        while let current = responder {
            if let application = current as? UIApplication {
                application.open(appURL, options: [:], completionHandler: nil)
                return
            }
            responder = current.next
        }
    }
}
