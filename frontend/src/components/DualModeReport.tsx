import { AlertTriangle, CheckCircle, Clock, Shield, AlertCircle, ChevronRight } from "lucide-react";
import type { Report, Verdict } from "../types";

interface DualModeReportProps {
  report: Report;
}

export default function DualModeReport({ report }: DualModeReportProps) {
  // Separate verdicts by mode
  const incidents = report.incidents.filter(v => v.mode !== "checklist");
  const checklistViolations = report.incidents.filter(v => v.mode === "checklist");
  
  // Get all checklist items (both compliant and non-compliant)
  const checklistItems = report.all_verdicts.filter(v => v.mode === "checklist");
  
  // Group checklist items by status
  const checklistCompliant = checklistItems.filter(v => v.compliant);
  const checklistPending = checklistItems.filter(v => !v.compliant);

  const getSeverityColor = (severity: string) => {
    switch (severity) {
      case "critical": return "text-red-600 bg-red-50 border-red-200";
      case "high": return "text-orange-600 bg-orange-50 border-orange-200";
      case "medium": return "text-yellow-600 bg-yellow-50 border-yellow-200";
      case "low": return "text-green-600 bg-green-50 border-green-200";
      default: return "text-gray-600 bg-gray-50 border-gray-200";
    }
  };

  const getSeverityIcon = (severity: string) => {
    switch (severity) {
      case "critical": return <AlertTriangle className="w-4 h-4" />;
      case "high": return <AlertCircle className="w-4 h-4" />;
      default: return <Shield className="w-4 h-4" />;
    }
  };

  return (
    <div className="space-y-6">
      {/* Summary Card */}
      <div className={`p-4 rounded-lg border ${
        report.overall_compliant 
          ? "bg-green-50 border-green-200" 
          : "bg-red-50 border-red-200"
      }`}>
        <div className="flex items-start gap-3">
          {report.overall_compliant ? (
            <CheckCircle className="w-5 h-5 text-green-600 mt-0.5" />
          ) : (
            <AlertTriangle className="w-5 h-5 text-red-600 mt-0.5" />
          )}
          <div className="flex-1">
            <h3 className="font-semibold text-gray-900">
              {report.overall_compliant ? "Compliant" : "Non-Compliant"}
            </h3>
            <p className="text-sm text-gray-600 mt-1">{report.summary}</p>
          </div>
        </div>
      </div>

      {/* Dual Mode Sections */}
      <div className="grid lg:grid-cols-2 gap-6">
        {/* Incidents Section (Always Alert) */}
        <div className="space-y-3">
          <div className="flex items-center gap-2 pb-2 border-b">
            <AlertTriangle className="w-5 h-5 text-red-500" />
            <h3 className="font-semibold text-gray-900">
              Incidents
              {incidents.length > 0 && (
                <span className="ml-2 px-2 py-0.5 bg-red-100 text-red-700 text-xs rounded-full">
                  {incidents.length}
                </span>
              )}
            </h3>
          </div>
          
          {incidents.length === 0 ? (
            <div className="text-sm text-gray-500 py-4 text-center">
              No incidents detected
            </div>
          ) : (
            <div className="space-y-2">
              {incidents.map((incident, idx) => (
                <div
                  key={idx}
                  className={`p-3 rounded-lg border ${getSeverityColor(incident.severity)}`}
                >
                  <div className="flex items-start gap-2">
                    {getSeverityIcon(incident.severity)}
                    <div className="flex-1 min-w-0">
                      <div className="text-sm font-medium text-gray-900">
                        {incident.rule_description}
                      </div>
                      <div className="text-xs text-gray-600 mt-1">
                        {incident.reason}
                      </div>
                      {incident.timestamp !== null && (
                        <div className="text-xs text-gray-500 mt-1">
                          @ {incident.timestamp.toFixed(1)}s
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Checklist Section (Check Once) */}
        <div className="space-y-3">
          <div className="flex items-center gap-2 pb-2 border-b">
            <CheckCircle className="w-5 h-5 text-blue-500" />
            <h3 className="font-semibold text-gray-900">
              Compliance Checklist
              {checklistCompliant.length > 0 && (
                <span className="ml-2 px-2 py-0.5 bg-green-100 text-green-700 text-xs rounded-full">
                  {checklistCompliant.length}/{checklistItems.length}
                </span>
              )}
            </h3>
          </div>

          {/* Checklist fulfilled banner */}
          {report.checklist_fulfilled === true && checklistItems.length > 0 && (
            <div className="p-3 rounded-lg border bg-green-50 border-green-200">
              <div className="flex items-center gap-2">
                <CheckCircle className="w-4 h-4 text-green-600" />
                <span className="text-sm font-medium text-green-800">All checklist items fulfilled</span>
              </div>
            </div>
          )}
          {report.checklist_fulfilled === false && checklistItems.length > 0 && (
            <div className="p-3 rounded-lg border bg-red-50 border-red-200">
              <div className="flex items-center gap-2">
                <AlertTriangle className="w-4 h-4 text-red-600" />
                <span className="text-sm font-medium text-red-800">
                  Checklist not fulfilled — {checklistPending.length} of {checklistItems.length} item{checklistPending.length !== 1 ? "s" : ""} pending
                </span>
              </div>
            </div>
          )}

          {checklistItems.length === 0 ? (
            <div className="text-sm text-gray-500 py-4 text-center">
              No checklist items configured
            </div>
          ) : (
            <div className="space-y-2">
              {/* Compliant items */}
              {checklistCompliant.map((item, idx) => (
                <div
                  key={`compliant-${idx}`}
                  className="p-3 rounded-lg border bg-green-50 border-green-200"
                >
                  <div className="flex items-start gap-2">
                    <CheckCircle className="w-4 h-4 text-green-600 mt-0.5" />
                    <div className="flex-1">
                      <div className="text-sm text-gray-900">
                        {item.rule_description}
                      </div>
                      {item.expires_at && (
                        <div className="text-xs text-gray-500 mt-1 flex items-center gap-1">
                          <Clock className="w-3 h-3" />
                          Valid for {Math.round((item.expires_at - Date.now()/1000) / 60)} min
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              ))}

              {/* Pending/expired items */}
              {checklistPending.map((item, idx) => (
                <div
                  key={`pending-${idx}`}
                  className="p-3 rounded-lg border bg-yellow-50 border-yellow-200"
                >
                  <div className="flex items-start gap-2">
                    <Clock className="w-4 h-4 text-yellow-600 mt-0.5" />
                    <div className="flex-1">
                      <div className="text-sm text-gray-900">
                        {item.rule_description}
                      </div>
                      <div className="text-xs text-gray-600 mt-1">
                        {item.checklist_status === "expired" 
                          ? "Verification expired - needs renewal" 
                          : "Pending verification"}
                      </div>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Recommendations */}
      {report.recommendations && report.recommendations.length > 0 && (
        <div className="mt-6 p-4 bg-blue-50 border border-blue-200 rounded-lg">
          <h3 className="font-semibold text-gray-900 mb-2">Recommendations</h3>
          <ul className="space-y-1">
            {report.recommendations.map((rec, idx) => (
              <li key={idx} className="flex items-start gap-2 text-sm text-gray-700">
                <ChevronRight className="w-3 h-3 mt-1 text-blue-500" />
                <span>{rec}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}