import Foundation
import EventKit
import Cocoa

// CalHelper: Calendar event helper for TimeTracker
// Outputs calendar events as JSON to stdout and ~/.timetracker/cal_helper_output.json
//
// Usage:
//   open CalHelper.app --args --list-calendars
//   open CalHelper.app --args --events --start YYYY-MM-DD --end YYYY-MM-DD [--calendar "name"]
//
// Build:
//   swiftc -framework Cocoa -framework EventKit CalHelper.swift -o CalHelper.app/Contents/MacOS/CalHelper

class CalendarHelper {
    let store = EKEventStore()
    let args: [String]

    init() {
        self.args = CommandLine.arguments
    }

    func run() {
        let status = EKEventStore.authorizationStatus(for: .event)
        print("Auth status: \(status.rawValue)")
        // 0=notDetermined, 1=restricted, 2=denied, 3=authorized(deprecated), 4=fullAccess

        if status.rawValue >= 3 {
            print("Already authorized, querying directly...")
            handleCommand()
        } else if status == .notDetermined {
            store.requestFullAccessToEvents { granted, error in
                if granted {
                    DispatchQueue.main.async { self.handleCommand() }
                } else {
                    self.outputError("Calendar access denied")
                    exit(1)
                }
            }
            // Run loop to wait for callback
            RunLoop.main.run(until: Date(timeIntervalSinceNow: 10))
        } else {
            outputError("Calendar access not authorized (status: \(status.rawValue))")
            exit(1)
        }
    }

    func handleCommand() {
        // Give EventKit time to load sources
        store.refreshSourcesIfNecessary()
        Thread.sleep(forTimeInterval: 1.0)

        if args.contains("--list-calendars") {
            listCalendars()
        } else if args.contains("--events") {
            fetchEvents()
        } else {
            listCalendars()
        }
        exit(0)
    }

    func listCalendars() {
        let calendars = store.calendars(for: .event)
        var result: [[String: Any]] = []
        for cal in calendars {
            result.append([
                "title": cal.title,
                "source": cal.source.title,
                "sourceType": cal.source.sourceType.rawValue,
                "calendarIdentifier": cal.calendarIdentifier
            ])
        }
        outputJSON(result)
    }

    func fetchEvents() {
        let dateFormatter = DateFormatter()
        dateFormatter.dateFormat = "yyyy-MM-dd"

        var startDate = Calendar.current.startOfDay(for: Date())
        var endDate = Calendar.current.date(byAdding: .day, value: 1, to: startDate)!

        // Parse --start and --end arguments
        if let startIdx = args.firstIndex(of: "--start"), startIdx + 1 < args.count {
            if let d = dateFormatter.date(from: args[startIdx + 1]) {
                startDate = d
            }
        }
        if let endIdx = args.firstIndex(of: "--end"), endIdx + 1 < args.count {
            if let d = dateFormatter.date(from: args[endIdx + 1]) {
                endDate = d
            }
        }

        // Optional calendar filter
        var targetCalendars: [EKCalendar]? = nil
        if let calIdx = args.firstIndex(of: "--calendar"), calIdx + 1 < args.count {
            let calName = args[calIdx + 1]
            let allCals = store.calendars(for: .event)
            let matched = allCals.filter { $0.title == calName }
            if !matched.isEmpty {
                targetCalendars = matched
            }
        }

        let predicate = store.predicateForEvents(withStart: startDate, end: endDate, calendars: targetCalendars)
        let events = store.events(matching: predicate)

        let outputFormatter = DateFormatter()
        outputFormatter.dateFormat = "yyyy-MM-dd'T'HH:mm:ss"

        var result: [[String: Any]] = []
        for event in events {
            var dict: [String: Any] = [
                "title": event.title ?? "",
                "start_time": outputFormatter.string(from: event.startDate),
                "end_time": outputFormatter.string(from: event.endDate),
                "calendar": event.calendar.title,
                "event_id": event.eventIdentifier ?? "",
                "is_all_day": event.isAllDay
            ]
            if let location = event.location {
                dict["location"] = location
            }
            if let notes = event.notes {
                dict["description"] = notes
            }
            result.append(dict)
        }
        outputJSON(result)
    }

    func outputJSON(_ data: Any) {
        do {
            let jsonData = try JSONSerialization.data(withJSONObject: data, options: [.prettyPrinted, .sortedKeys])
            if let jsonString = String(data: jsonData, encoding: .utf8) {
                // Write to output file
                let outputPath = NSHomeDirectory() + "/.timetracker/cal_helper_output.json"
                try jsonString.write(toFile: outputPath, atomically: true, encoding: .utf8)
                print(jsonString)
            }
        } catch {
            let errMsg = "JSON serialization error: \(error)"
            let outputPath = NSHomeDirectory() + "/.timetracker/cal_helper_output.json"
            try? "{\"error\": \"\(errMsg)\"}".write(toFile: outputPath, atomically: true, encoding: .utf8)
        }
    }

    func outputError(_ message: String) {
        let error: [String: Any] = ["error": message]
        outputJSON(error)
    }
}

// Create NSApplication but don't show in dock
let app = NSApplication.shared
app.setActivationPolicy(.accessory)

let helper = CalendarHelper()
helper.run()

// If we reach here, run the event loop briefly
RunLoop.main.run(until: Date(timeIntervalSinceNow: 3))
