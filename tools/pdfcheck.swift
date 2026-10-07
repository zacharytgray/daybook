// prints {"pages": n, "text": "..."} for a pdf, using the system PDFKit
import Foundation
import PDFKit

let args = CommandLine.arguments
guard args.count == 2, let doc = PDFDocument(url: URL(fileURLWithPath: args[1])) else {
    FileHandle.standardError.write("cannot open pdf\n".data(using: .utf8)!)
    exit(1)
}
var text = ""
for i in 0..<doc.pageCount {
    text += (doc.page(at: i)?.string ?? "") + "\n\u{0C}\n"
}
let out: [String: Any] = ["pages": doc.pageCount, "text": text]
let data = try! JSONSerialization.data(withJSONObject: out)
FileHandle.standardOutput.write(data)
