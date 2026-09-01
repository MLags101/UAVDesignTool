%% Robust Airfoil to SolidWorks Converter
clear; clc;

% --- Configuration ---
inputFile = 'sd7037-il.csv';
outputFile = 'sd7037_for_solidworks.txt';
targetChord = 100; % Target chord in mm
originalChord = 100; % CSV base chord (usually 100 or 1)
scaleFactor = targetChord / originalChord;

% --- Process File ---
fid = fopen(inputFile, 'r');
if fid == -1, error('Cannot open file'); end

data = [];
foundSurface = false;

while ~feof(fid)
    tline = fgetl(fid);
    if ~ischar(tline), break; end
    
    % 1. Look for the start of the data section
    if contains(tline, 'Airfoil surface')
        foundSurface = true;
        fgetl(fid); % Skip the 'X(mm),Y(mm)' header line
        continue;
    end
    
    % 2. If we are in the data section, process coordinates
    if foundSurface
        % Stop if line is empty, just a comma, or starts a new section
        if isempty(strtrim(tline)) || strcmp(strtrim(tline), ',') || ...
           contains(tline, 'Camber line') || contains(tline, 'Chord line')
            break; 
        end
        
        % Parse CSV values
        vals = str2double(split(tline, ','));
        if numel(vals) >= 2
            % Store X, Y, and a 0 for Z
            data = [data; vals(1)*scaleFactor, vals(2)*scaleFactor, 0];
        end
    end
end
fclose(fid);

% --- Export ---
% Write tab-delimited file (SolidWorks format)
writematrix(data, outputFile, 'Delimiter', 'tab');

fprintf('Success! Extracted %d points.\n', size(data, 1));
fprintf('File "%s" is ready for SolidWorks.\n', outputFile);